import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import backup.backup_manager as backup_manager
from auth.permissions import can_view_backup_entry
import scheduler.scheduler as scheduler


class SchedulerTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_dir = self.root / "config"
        self.config_dir.mkdir()
        self.schedule_path = self.config_dir / "backup_schedule.json"
        self.history_path = self.config_dir / "backup_history.json"
        self.original_paths = {
            "SCHEDULE_PATH": backup_manager.SCHEDULE_PATH,
            "HISTORY_PATH": backup_manager.HISTORY_PATH,
        }
        backup_manager.SCHEDULE_PATH = str(self.schedule_path)
        backup_manager.HISTORY_PATH = str(self.history_path)
        self.history_path.write_text("[]", encoding="utf-8")

    def tearDown(self):
        backup_manager.SCHEDULE_PATH = self.original_paths["SCHEDULE_PATH"]
        backup_manager.HISTORY_PATH = self.original_paths["HISTORY_PATH"]
        self.temp.cleanup()

    def write_schedule(self, **overrides):
        schedule = {
            "time_start": "08:00",
            "time_end": "09:00",
            "scheduled_username": "dudu",
            "scheduled_user_role": "operator",
            "scheduled_company_id": "default",
        }
        schedule.update(overrides)
        self.schedule_path.write_text(
            json.dumps(schedule, indent=4),
            encoding="utf-8"
        )

    def load_schedule(self):
        return json.loads(self.schedule_path.read_text(encoding="utf-8"))

    def load_history(self):
        return json.loads(self.history_path.read_text(encoding="utf-8"))

    def test_scheduled_backup_runs_as_user_who_saved_schedule(self):
        self.write_schedule()
        now = datetime(2026, 5, 20, 8, 30, 0)

        with patch.object(
            scheduler,
            "run_backup_job",
            return_value={"backup_path": "snapshot.json"}
        ) as run_backup:
            self.assertTrue(scheduler.execute_scheduled_backup_once(now))

        run_backup.assert_called_once_with(
            trigger="agendado",
            username="dudu",
            user_role="operator",
            company_id="default",
            now=now
        )
        schedule = self.load_schedule()
        self.assertEqual("executed", schedule["status"])
        self.assertEqual("2026-05-20T08:30:00", schedule["last_run_at"])
        self.assertEqual("2026-05-20T08:30:00", schedule["last_success_at"])
        self.assertEqual("", schedule["last_error"])

    def test_scheduled_backup_failure_is_recorded_and_not_retried_same_day(self):
        self.write_schedule()
        now = datetime(2026, 5, 20, 8, 30, 0)

        with patch.object(
            scheduler,
            "run_backup_job",
            side_effect=RuntimeError("disk full")
        ):
            self.assertFalse(scheduler.execute_scheduled_backup_once(now))

        schedule = self.load_schedule()
        self.assertEqual("failed", schedule["status"])
        self.assertEqual("2026-05-20T08:30:00", schedule["last_run_at"])
        self.assertEqual("disk full", schedule["last_error"])
        self.assertFalse(backup_manager.is_schedule_due(now))

        history = self.load_history()
        self.assertEqual(1, len(history))
        self.assertEqual("failed", history[0]["status"])
        self.assertEqual("agendado", history[0]["trigger"])
        self.assertEqual("dudu", history[0]["user"])
        self.assertIn("disk full", history[0]["backup_description"])

    def test_scheduled_backup_is_skipped_when_manual_backup_is_running(self):
        self.write_schedule()
        now = datetime(2026, 5, 20, 8, 30, 0)
        acquired = backup_manager._BACKUP_EXECUTION_LOCK.acquire(blocking=False)
        self.addCleanup(
            lambda: backup_manager._BACKUP_EXECUTION_LOCK.release()
            if acquired and backup_manager._BACKUP_EXECUTION_LOCK.locked()
            else None
        )

        with patch.object(scheduler, "run_backup_job") as run_backup:
            self.assertIsNone(scheduler.execute_scheduled_backup_once(now))

        run_backup.assert_not_called()

    def test_operator_can_see_legacy_system_scheduled_backups(self):
        current_user = {
            "username": "dudu",
            "role": "operator",
            "company_id": "default",
        }
        entry = {
            "trigger": "agendado",
            "user": "sistema",
            "user_role": "system",
            "company_id": "default",
        }

        self.assertTrue(can_view_backup_entry(current_user, entry))

    def test_non_default_company_user_can_see_legacy_system_scheduled_backups(self):
        current_user = {
            "username": "diogosonegueti@gmail.com",
            "role": "admin",
            "company_id": "company_diogo",
        }
        entry = {
            "trigger": "politica_prioridade",
            "user": "sistema",
            "user_role": "system",
            "company_id": "default",
        }

        self.assertTrue(can_view_backup_entry(current_user, entry))

    def test_scheduler_exits_as_soon_as_shutdown_wait_is_triggered(self):
        with patch.object(scheduler, "is_shutdown_requested", return_value=False):
            with patch.object(scheduler, "execute_scheduled_backup_once") as execute:
                with patch.object(
                    scheduler,
                    "is_priority_backup_policy_enabled",
                    return_value=False
                ):
                    with patch.object(
                        scheduler,
                        "get_priority_scheduler_check_interval_seconds",
                        return_value=600
                    ):
                        with patch.object(
                            scheduler,
                            "wait_for_shutdown",
                            return_value=True
                        ) as wait_for_shutdown:
                            scheduler.start_scheduler()

        execute.assert_called_once()
        wait_for_shutdown.assert_called_once_with(20)

    def test_priority_policy_runs_with_saved_schedule_user_context(self):
        self.write_schedule(
            scheduled_username="diogosonegueti@gmail.com",
            scheduled_user_role="admin",
            scheduled_company_id="company_diogo",
        )

        with patch.object(scheduler, "is_shutdown_requested", return_value=False):
            with patch.object(scheduler, "execute_scheduled_backup_once"):
                with patch.object(
                    scheduler,
                    "is_priority_backup_policy_enabled",
                    return_value=True
                ):
                    with patch.object(
                        scheduler,
                        "get_priority_scheduler_check_interval_seconds",
                        return_value=60
                    ):
                        with patch.object(
                            scheduler,
                            "is_backup_job_running",
                            return_value=False
                        ):
                            with patch.object(
                                scheduler,
                                "run_priority_backup_job",
                                return_value={"skipped": True, "reason": "teste"}
                            ) as run_priority:
                                with patch.object(
                                    scheduler,
                                    "wait_for_shutdown",
                                    return_value=True
                                ):
                                    scheduler.start_scheduler()

        run_priority.assert_called_once()
        self.assertEqual(
            "diogosonegueti@gmail.com",
            run_priority.call_args.kwargs["username"],
        )
        self.assertEqual("admin", run_priority.call_args.kwargs["user_role"])
        self.assertEqual("company_diogo", run_priority.call_args.kwargs["company_id"])


if __name__ == "__main__":
    unittest.main()
