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
            company_id="default"
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


if __name__ == "__main__":
    unittest.main()
