import json
import json
import gzip
import os
import threading
import tempfile
import unittest
import zipfile
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import backup.backup_manager as backup_manager
from backup.backup_manager import build_priority_eligible_manifest
from backup.backup_manager import export_snapshot_to_zip
from backup.backup_manager import get_backup_interval
from backup.backup_manager import get_priority_scheduler_check_interval_seconds
from backup.backup_manager import is_dev_mode_enabled
from backup.backup_manager import is_file_eligible_for_backup
from backup.backup_manager import load_incremental_index
from backup.backup_manager import normalize_archive_name
from backup.backup_manager import normalize_path
from backup.backup_manager import restore_snapshot
from backup.backup_manager import run_incremental_backup
from backup.backup_manager import run_backup_job
from backup.backup_manager import run_priority_backup_job


class IncrementalBackupTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "backups"
        self.source.mkdir()
        self.destination.mkdir()
        self.now = datetime(2026, 5, 8, 8, 0, 0)
        self.original_dev_mode = os.environ.get("BACKUP_DEV_MODE")
        backup_manager._BACKUP_ENV_FILE_LOADED = True
        os.environ.pop("BACKUP_DEV_MODE", None)
        self.original_paths = {
            "CONFIG_PATH": backup_manager.CONFIG_PATH,
            "DATASET_PATH": backup_manager.DATASET_PATH,
            "HISTORY_PATH": backup_manager.HISTORY_PATH,
            "PRIORITY_STATE_PATH": backup_manager.PRIORITY_STATE_PATH,
        }

    def tearDown(self):
        if self.original_dev_mode is None:
            os.environ.pop("BACKUP_DEV_MODE", None)
        else:
            os.environ["BACKUP_DEV_MODE"] = self.original_dev_mode

        backup_manager._BACKUP_ENV_FILE_LOADED = True
        backup_manager.CONFIG_PATH = self.original_paths["CONFIG_PATH"]
        backup_manager.DATASET_PATH = self.original_paths["DATASET_PATH"]
        backup_manager.HISTORY_PATH = self.original_paths["HISTORY_PATH"]
        backup_manager.PRIORITY_STATE_PATH = self.original_paths["PRIORITY_STATE_PATH"]
        self.temp.cleanup()

    def write_file(self, relative_path, content):
        path = self.source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_incremental_objects_use_maximum_gzip_compression_level(self):
        self.assertEqual(backup_manager.OBJECT_COMPRESSION_LEVEL, 9)

    def manifest_for(self, *paths):
        return [
            (
                str(path),
                normalize_archive_name(f"source/{path.relative_to(self.source)}")
            )
            for path in paths
        ]

    def priority_index_for(self, manifest, priority):
        by_source_path = {}
        by_archive_name = {}

        for source_path, archive_name in manifest:
            row = {
                "source_path": source_path,
                "archive_name": archive_name,
                "priority": priority,
                "priority_score": "80" if priority == "alta" else "20",
            }
            by_source_path[normalize_path(source_path)] = row
            by_archive_name[normalize_archive_name(archive_name)] = row

        return {
            "by_source_path": by_source_path,
            "by_archive_name": by_archive_name,
        }

    def mixed_priority_index_for(self, priority_by_archive_name):
        by_source_path = {}
        by_archive_name = {}

        for source_path, archive_name, priority in priority_by_archive_name:
            row = {
                "source_path": source_path,
                "archive_name": archive_name,
                "priority": priority,
                "priority_score": "80" if priority == "alta" else "20",
            }
            by_source_path[normalize_path(source_path)] = row
            by_archive_name[normalize_archive_name(archive_name)] = row

        return {
            "by_source_path": by_source_path,
            "by_archive_name": by_archive_name,
        }

    def configure_priority_job_environment(self, files, priority):
        config_path = self.root / "config" / "config.json"
        dataset_path = self.root / "dataset" / "files_dataset.csv"
        history_path = self.root / "config" / "backup_history.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_path.parent.mkdir(parents=True, exist_ok=True)

        backup_manager.CONFIG_PATH = str(config_path)
        backup_manager.DATASET_PATH = str(dataset_path)
        backup_manager.HISTORY_PATH = str(history_path)
        backup_manager.PRIORITY_STATE_PATH = str(
            self.root / "config" / "priority_backup_state.json"
        )

        config_path.write_text(
            json.dumps(
                {
                    "directories": [str(self.source)],
                    "backup_destination": str(self.destination),
                    "priority_backup_policy_enabled": True,
                }
            ),
            encoding="utf-8"
        )
        history_path.write_text("[]", encoding="utf-8")

        rows = [
            (
                "name,source_path,archive_name,priority,priority_score,"
                "file_hash\n"
            )
        ]

        for file_path in files:
            archive_name = normalize_archive_name(
                f"source/{file_path.relative_to(self.source)}"
            )
            rows.append(
                (
                    f"{file_path.name},{file_path},{archive_name},"
                    f"{priority},80,\n"
                )
            )

        dataset_path.write_text("".join(rows), encoding="utf-8")

    def object_paths(self):
        return [
            path
            for path in self.destination.rglob("*")
            if path.is_file() and path.parent.name == backup_manager.OBJECTS_DIRNAME
        ]

    def load_snapshot(self, snapshot_path):
        return json.loads(Path(snapshot_path).read_text(encoding="utf-8"))

    def run_backup(self, manifest, now=None, priority_policy=False, priority="media"):
        return run_incremental_backup(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            manifest=manifest,
            now=now or self.now,
            priority_policy=priority_policy,
            priority_index=self.priority_index_for(manifest, priority),
        )

    def run_user_backup(
        self,
        manifest,
        username="sistema",
        now=None,
        priority_policy=False,
        priority="media"
    ):
        user_destination = backup_manager.get_user_backup_destination(
            str(self.destination),
            username
        )
        return run_incremental_backup(
            directories=[str(self.source)],
            backup_destination=user_destination,
            manifest=manifest,
            now=now or self.now,
            priority_policy=priority_policy,
            priority_index=self.priority_index_for(manifest, priority),
        )

    def test_dev_mode_absent_uses_real_intervals(self):
        self.assertFalse(is_dev_mode_enabled())
        self.assertEqual(timedelta(days=7), get_backup_interval("baixa"))
        self.assertEqual(timedelta(days=2), get_backup_interval("media"))
        self.assertEqual(timedelta(hours=4), get_backup_interval("alta"))

    def test_dev_mode_false_uses_real_intervals(self):
        os.environ["BACKUP_DEV_MODE"] = "false"

        self.assertFalse(is_dev_mode_enabled())
        self.assertEqual(timedelta(days=7), get_backup_interval("baixa"))
        self.assertEqual(timedelta(days=2), get_backup_interval("media"))
        self.assertEqual(timedelta(hours=4), get_backup_interval("alta"))

    def test_dev_mode_true_uses_reduced_intervals(self):
        os.environ["BACKUP_DEV_MODE"] = "TrUe"

        self.assertTrue(is_dev_mode_enabled())
        self.assertEqual(timedelta(minutes=30), get_backup_interval("baixa"))
        self.assertEqual(timedelta(minutes=15), get_backup_interval("media"))
        self.assertEqual(timedelta(minutes=5), get_backup_interval("alta"))

    def test_priority_scheduler_check_interval_changes_in_dev_mode(self):
        self.assertEqual(600, get_priority_scheduler_check_interval_seconds())

        os.environ["BACKUP_DEV_MODE"] = "true"

        self.assertEqual(60, get_priority_scheduler_check_interval_seconds())

    def test_priority_job_skips_when_no_file_is_eligible(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        file_path = self.write_file("A.txt", "v1")
        manifest = self.manifest_for(file_path)
        self.configure_priority_job_environment([file_path], "alta")
        self.run_user_backup(manifest, now=datetime.now(), priority="alta")

        result = run_priority_backup_job(
            run_scan_first=False,
            username="sistema",
            user_role="system"
        )

        self.assertTrue(result["skipped"])
        self.assertEqual(
            "Nenhum arquivo elegivel pela politica de prioridade.",
            result["reason"]
        )
        self.assertEqual(0, len(backup_manager.load_history()))
        self.assertEqual(1, len(result["priority_decisions"]))
        self.assertFalse(result["priority_decisions"][0]["included"])

    def test_priority_eligible_manifest_in_dev_mode_includes_high_after_change(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        file_path = self.write_file("A.txt", "v1")
        manifest = self.manifest_for(file_path)
        priority_index = self.priority_index_for(manifest, "alta")
        self.run_backup(manifest, priority="alta")

        before_manifest, before_decisions, _ = build_priority_eligible_manifest(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            now=self.now + timedelta(minutes=4),
            priority_index=priority_index,
        )
        after_manifest, after_decisions, _ = build_priority_eligible_manifest(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            now=self.now + timedelta(minutes=5, seconds=1),
            priority_index=priority_index,
        )
        file_path.write_text("v2", encoding="utf-8")
        changed_manifest, changed_decisions, _ = build_priority_eligible_manifest(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            now=self.now + timedelta(minutes=5, seconds=2),
            priority_index=priority_index,
        )

        self.assertEqual([], before_manifest)
        self.assertFalse(before_decisions[0]["included"])
        self.assertEqual([], after_manifest)
        self.assertFalse(after_decisions[0]["included"])
        self.assertEqual(
            "arquivo sem alteracao desde a ultima snapshot",
            after_decisions[0]["reason"]
        )
        self.assertEqual(
            [(manifest[0][0], normalize_archive_name(manifest[0][1]))],
            [
                (
                    changed_manifest[0][0],
                    normalize_archive_name(changed_manifest[0][1])
                )
            ]
        )
        self.assertTrue(changed_decisions[0]["included"])

    def test_priority_eligible_manifest_in_dev_mode_respects_medium_and_low(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        medium_dir = self.root / "medium_source"
        low_dir = self.root / "low_source"
        medium_dir.mkdir()
        low_dir.mkdir()
        medium_file = medium_dir / "M.txt"
        low_file = low_dir / "L.txt"
        medium_file.write_text("media", encoding="utf-8")
        low_file.write_text("baixa", encoding="utf-8")
        medium_manifest = [
            (str(medium_file), normalize_archive_name("medium_source/M.txt"))
        ]
        low_manifest = [
            (str(low_file), normalize_archive_name("low_source/L.txt"))
        ]
        medium_index = self.priority_index_for(medium_manifest, "media")
        low_index = self.priority_index_for(low_manifest, "baixa")
        run_incremental_backup(
            directories=[str(medium_dir)],
            backup_destination=str(self.destination),
            manifest=medium_manifest,
            now=self.now,
            priority_policy=True,
            priority_index=medium_index,
        )
        run_incremental_backup(
            directories=[str(low_dir)],
            backup_destination=str(self.destination),
            manifest=low_manifest,
            now=self.now,
            priority_policy=True,
            priority_index=low_index,
        )

        medium_before, _, _ = build_priority_eligible_manifest(
            directories=[str(medium_dir)],
            backup_destination=str(self.destination),
            now=self.now + timedelta(minutes=14),
            priority_index=medium_index,
        )
        medium_file.write_text("media alterada", encoding="utf-8")
        medium_after, _, _ = build_priority_eligible_manifest(
            directories=[str(medium_dir)],
            backup_destination=str(self.destination),
            now=self.now + timedelta(minutes=15, seconds=1),
            priority_index=medium_index,
        )
        low_before, _, _ = build_priority_eligible_manifest(
            directories=[str(low_dir)],
            backup_destination=str(self.destination),
            now=self.now + timedelta(minutes=29),
            priority_index=low_index,
        )
        low_after, low_after_decisions, _ = build_priority_eligible_manifest(
            directories=[str(low_dir)],
            backup_destination=str(self.destination),
            now=self.now + timedelta(minutes=30, seconds=1),
            priority_index=low_index,
        )

        self.assertEqual([], medium_before)
        self.assertEqual(
            [(medium_manifest[0][0], normalize_archive_name(medium_manifest[0][1]))],
            [(medium_after[0][0], normalize_archive_name(medium_after[0][1]))]
        )
        self.assertEqual([], low_before)
        self.assertEqual([], low_after)
        self.assertFalse(low_after_decisions[0]["included"])
        self.assertEqual(
            "baixa prioridade aguardando backup completo",
            low_after_decisions[0]["reason"]
        )

    def test_first_backup_creates_objects_snapshot_and_index(self):
        files = [
            self.write_file("A.txt", "a"),
            self.write_file("B.txt", "b"),
            self.write_file("C.txt", "c"),
        ]
        result = self.run_backup(self.manifest_for(*files))

        self.assertEqual(3, len(self.object_paths()))
        self.assertTrue(Path(result["snapshot_path"]).exists())
        self.assertEqual(
            self.destination / "2026-05-08" / backup_manager.SNAPSHOTS_DIRNAME,
            Path(result["snapshot_path"]).parent
        )
        self.assertEqual(str(self.destination), result["backup_storage"])
        self.assertEqual(3, len(self.load_snapshot(result["snapshot_path"])["files"]))
        self.assertEqual(
            3,
            len(load_incremental_index(str(self.destination))["files"])
        )

    def test_second_backup_without_changes_creates_no_new_object(self):
        files = [
            self.write_file("A.txt", "a"),
            self.write_file("B.txt", "b"),
            self.write_file("C.txt", "c"),
        ]
        manifest = self.manifest_for(*files)
        self.run_backup(manifest)
        result = self.run_backup(manifest, now=self.now + timedelta(seconds=1))

        self.assertEqual(3, len(self.object_paths()))
        self.assertEqual(3, result["status_counts"]["skipped_unchanged"])

    def test_new_file_adds_only_one_new_object(self):
        files = [
            self.write_file("A.txt", "a"),
            self.write_file("B.txt", "b"),
            self.write_file("C.txt", "c"),
        ]
        self.run_backup(self.manifest_for(*files))
        files.append(self.write_file("D.txt", "d"))
        result = self.run_backup(
            self.manifest_for(*files),
            now=self.now + timedelta(seconds=1)
        )

        self.assertEqual(4, len(self.object_paths()))
        self.assertEqual(1, result["objects_stored"])

    def test_changed_file_creates_new_version(self):
        files = [
            self.write_file("A.txt", "a"),
            self.write_file("B.txt", "b"),
            self.write_file("C.txt", "c"),
        ]
        manifest = self.manifest_for(*files)
        self.run_backup(manifest)
        files[1].write_text("b changed", encoding="utf-8")
        result = self.run_backup(manifest, now=self.now + timedelta(seconds=1))

        self.assertEqual(4, len(self.object_paths()))
        self.assertEqual(1, result["objects_stored"])

    def test_duplicate_files_share_one_physical_object(self):
        original = self.write_file("A.txt", "same")
        copy = self.write_file("copia_de_A.txt", "same")
        result = self.run_backup(self.manifest_for(original, copy))
        hashes = {
            item["hash"]
            for item in self.load_snapshot(result["snapshot_path"])["files"]
        }

        self.assertEqual(1, len(self.object_paths()))
        self.assertEqual(1, len(hashes))
        self.assertEqual(1, result["objects_stored"])
        self.assertEqual(1, result["objects_referenced"])

    def test_duplicate_files_restore_after_sources_are_deleted(self):
        original = self.write_file("A.txt", "same")
        copy = self.write_file("nested/copia_de_A.txt", "same")
        result = self.run_backup(self.manifest_for(original, copy))
        restore_destination = self.root / "restore"
        original.unlink()
        copy.unlink()

        restore_snapshot(result["snapshot_path"], str(restore_destination))

        self.assertEqual(
            "same",
            (restore_destination / "source" / "A.txt").read_text(encoding="utf-8")
        )
        self.assertEqual(
            "same",
            (
                restore_destination / "source" / "nested" / "copia_de_A.txt"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(1, len(self.object_paths()))

    def test_low_priority_waits_seven_days_before_new_object(self):
        file_path = self.write_file("A.txt", "v1")
        manifest = self.manifest_for(file_path)
        self.run_backup(manifest, priority="baixa")
        file_path.write_text("v2", encoding="utf-8")
        result = self.run_backup(
            manifest,
            now=self.now + timedelta(days=1),
            priority_policy=True,
            priority="baixa"
        )

        self.assertEqual(1, len(self.object_paths()))
        self.assertEqual(1, result["files_not_eligible"])

    def test_low_priority_in_dev_mode_is_eligible_after_30_minutes(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        index_entry = {
            "last_priority": "baixa",
            "last_backup_at": self.now.isoformat(timespec="seconds"),
        }
        file_metadata = {"priority": "baixa"}

        self.assertFalse(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(minutes=29)
            )
        )
        self.assertTrue(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(minutes=30, seconds=1)
            )
        )

    def test_medium_priority_in_dev_mode_is_eligible_after_15_minutes(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        index_entry = {
            "last_priority": "media",
            "last_backup_at": self.now.isoformat(timespec="seconds"),
        }
        file_metadata = {"priority": "media"}

        self.assertFalse(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(minutes=14)
            )
        )
        self.assertTrue(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(minutes=15, seconds=1)
            )
        )

    def test_high_priority_saves_after_four_hours_only_when_changed(self):
        file_path = self.write_file("A.txt", "v1")
        manifest = self.manifest_for(file_path)
        self.run_backup(manifest, priority="alta")
        file_path.write_text("v2", encoding="utf-8")
        changed = self.run_backup(
            manifest,
            now=self.now + timedelta(hours=4, seconds=1),
            priority_policy=True,
            priority="alta"
        )
        unchanged = self.run_backup(
            manifest,
            now=self.now + timedelta(hours=8, seconds=2),
            priority_policy=True,
            priority="alta"
        )

        self.assertEqual(2, len(self.object_paths()))
        self.assertEqual(1, changed["objects_stored"])
        self.assertEqual(1, unchanged["files_unchanged"])

    def test_high_priority_in_dev_mode_is_eligible_after_5_minutes(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        index_entry = {
            "last_priority": "alta",
            "last_backup_at": self.now.isoformat(timespec="seconds"),
            "last_daily_backup_date": self.now.date().isoformat(),
        }
        file_metadata = {"priority": "alta"}

        self.assertFalse(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(minutes=4)
            )
        )
        self.assertTrue(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(minutes=5, seconds=1)
            )
        )

    def test_high_priority_in_production_keeps_daily_gate_and_4_hours(self):
        index_entry = {
            "last_priority": "alta",
            "last_backup_at": self.now.isoformat(timespec="seconds"),
            "last_daily_backup_date": self.now.date().isoformat(),
        }
        file_metadata = {"priority": "alta"}

        self.assertFalse(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(hours=3, minutes=59)
            )
        )
        self.assertTrue(
            is_file_eligible_for_backup(
                file_metadata,
                index_entry,
                self.now + timedelta(hours=4, seconds=1)
            )
        )
        self.assertTrue(
            is_file_eligible_for_backup(
                file_metadata,
                {
                    "last_priority": "alta",
                    "last_backup_at": self.now.isoformat(timespec="seconds"),
                    "last_daily_backup_date": "2026-05-07",
                },
                self.now + timedelta(minutes=1)
            )
        )

    def test_priority_job_creates_snapshot_when_file_is_eligible_in_dev_mode(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        file_path = self.write_file("A.txt", "v1")
        manifest = self.manifest_for(file_path)
        self.configure_priority_job_environment([file_path], "alta")
        self.run_user_backup(
            manifest,
            now=datetime.now() - timedelta(minutes=6),
            priority="alta"
        )
        file_path.write_text("v2", encoding="utf-8")

        result = run_priority_backup_job(
            run_scan_first=False,
            username="sistema",
            user_role="system"
        )

        self.assertFalse(result.get("skipped", False))
        self.assertEqual("incremental", result["storage_mode"])
        self.assertTrue(Path(result["snapshot_path"]).exists())
        self.assertEqual(1, len(backup_manager.load_history()))
        self.assertEqual(1, len(result["priority_decisions"]))
        self.assertTrue(result["priority_decisions"][0]["included"])

    def test_priority_job_skips_after_ttl_when_file_is_unchanged(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        file_path = self.write_file("A.txt", "v1")
        manifest = self.manifest_for(file_path)
        self.configure_priority_job_environment([file_path], "alta")
        self.run_user_backup(
            manifest,
            now=datetime.now() - timedelta(minutes=6),
            priority="alta"
        )

        result = run_priority_backup_job(
            run_scan_first=False,
            username="sistema",
            user_role="system"
        )

        self.assertTrue(result["skipped"])
        self.assertEqual(0, len(backup_manager.load_history()))
        self.assertEqual(
            "arquivo sem alteracao desde a ultima snapshot",
            result["priority_decisions"][0]["reason"]
        )

    def test_priority_job_marks_partial_backup_without_false_deletions(self):
        high_file = self.write_file("A.txt", "high")
        low_file = self.write_file("B.txt", "low")
        manifest = self.manifest_for(high_file, low_file)
        mixed_priority_index = self.mixed_priority_index_for(
            [
                (manifest[0][0], manifest[0][1], "alta"),
                (manifest[1][0], manifest[1][1], "baixa"),
            ]
        )
        self.configure_priority_job_environment([high_file, low_file], "alta")
        dataset_path = Path(backup_manager.DATASET_PATH)
        dataset_path.write_text(
            (
                "name,source_path,archive_name,priority,priority_score,file_hash\n"
                f"{high_file.name},{manifest[0][0]},{manifest[0][1]},alta,80,\n"
                f"{low_file.name},{manifest[1][0]},{manifest[1][1]},baixa,20,\n"
            ),
            encoding="utf-8"
        )

        full_result = run_incremental_backup(
            directories=[str(self.source)],
            backup_destination=backup_manager.get_user_backup_destination(
                str(self.destination),
                "sistema"
            ),
            manifest=manifest,
            now=self.now,
            priority_index=mixed_priority_index,
        )
        backup_manager.append_history(
            {
                "timestamp": self.now.strftime("%d/%m/%Y %H:%M:%S"),
                "backup_name": "full",
                "snapshot_id": full_result["snapshot_id"],
                "snapshot_path": full_result["snapshot_path"],
                "backup_path": full_result["snapshot_path"],
                "backup_storage": full_result["backup_storage"],
                "storage_mode": "incremental",
                "file_snapshot": full_result["file_snapshot"],
                "file_changes": [],
                "user": "sistema",
                "user_role": "system",
                "company_id": "default",
                "history_group_type": "full",
            }
        )
        high_file.write_text("high changed", encoding="utf-8")

        result = run_priority_backup_job(
            run_scan_first=False,
            username="sistema",
            user_role="system"
        )

        self.assertFalse(result.get("skipped", False))
        self.assertTrue(result.get("partial_backup"))
        self.assertEqual(
            ["alterado"],
            [change["action"] for change in result["file_changes"]]
        )
        self.assertEqual(full_result["snapshot_id"], result["parent_snapshot_id"])
        self.assertEqual("alta", result["priority_scope"])

        latest_full_snapshot = backup_manager.get_latest_history_snapshot()
        self.assertEqual(2, len(latest_full_snapshot))

    def test_incremental_deduplication_still_works_in_dev_mode(self):
        os.environ["BACKUP_DEV_MODE"] = "true"
        original = self.write_file("A.txt", "same")
        copy = self.write_file("copia_de_A.txt", "same")
        result = self.run_backup(
            self.manifest_for(original, copy),
            priority_policy=True,
            priority="alta"
        )

        self.assertEqual(1, len(self.object_paths()))
        self.assertEqual(1, result["objects_stored"])
        self.assertEqual(1, result["objects_referenced"])

    def test_restore_snapshot_recreates_folders_and_renames_conflict(self):
        file_path = self.write_file("nested/A.txt", "snapshot data")
        result = self.run_backup(self.manifest_for(file_path))
        restore_destination = self.root / "restore"

        first_restore = restore_snapshot(
            result["snapshot_path"],
            str(restore_destination)
        )
        restored_file = restore_destination / "source" / "nested" / "A.txt"
        restored_file.write_text("local conflict", encoding="utf-8")
        second_restore = restore_snapshot(
            result["snapshot_path"],
            str(restore_destination),
            conflict_strategy="rename"
        )
        renamed_file = restore_destination / "source" / "nested" / "A_recuperado.txt"

        self.assertEqual("restored", first_restore[0]["status"])
        self.assertEqual("local conflict", restored_file.read_text(encoding="utf-8"))
        self.assertTrue(renamed_file.exists())
        self.assertEqual("restored_renamed", second_restore[0]["status"])

    def test_export_snapshot_to_zip_contains_latest_files(self):
        first = self.write_file("docs/A.txt", "a")
        second = self.write_file("docs/B.txt", "b")
        result = self.run_backup(self.manifest_for(first, second))
        destination_zip = self.root / "exports" / "ultimo_backup.zip"

        export_result = export_snapshot_to_zip(
            result["snapshot_path"],
            str(destination_zip)
        )

        self.assertTrue(destination_zip.exists())
        self.assertEqual(2, export_result["files_exported"])
        self.assertEqual([], export_result["warnings"])

        with zipfile.ZipFile(destination_zip, "r") as archive:
            self.assertEqual(
                ["source/docs/A.txt", "source/docs/B.txt"],
                sorted(archive.namelist())
            )
            self.assertEqual(
                "a",
                archive.read("source/docs/A.txt").decode("utf-8")
            )
            self.assertEqual(
                "b",
                archive.read("source/docs/B.txt").decode("utf-8")
            )

    def test_export_snapshot_to_zip_reads_legacy_gzip_objects(self):
        source_file = self.write_file("docs/legado.txt", "conteudo legado")
        result = self.run_backup(self.manifest_for(source_file))
        snapshot = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
        object_path = (
            Path(result["backup_storage"])
            / snapshot["files"][0]["object_path"].replace("/", os.sep)
        )
        object_path.write_bytes(gzip.compress("conteudo legado".encode("utf-8")))
        destination_zip = self.root / "exports" / "backup_legado.zip"

        export_result = export_snapshot_to_zip(
            result["snapshot_path"],
            str(destination_zip)
        )

        self.assertEqual([], export_result["warnings"])
        with zipfile.ZipFile(destination_zip, "r") as archive:
            self.assertEqual(
                "conteudo legado",
                archive.read("source/docs/legado.txt").decode("utf-8")
            )

    def test_backup_job_separates_storage_by_user(self):
        backup_manager.HISTORY_PATH = str(self.root / "config" / "backup_history.json")
        file_path = self.write_file("A.txt", "a")

        alice = run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Alice",
            user_role="operator",
            company_id="default",
            now=self.now,
            run_scan_first=False,
        )
        bob = run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Bob",
            user_role="operator",
            company_id="default",
            now=self.now,
            run_scan_first=False,
        )

        self.assertTrue(file_path.exists())
        self.assertTrue(Path(alice["snapshot_path"]).exists())
        self.assertTrue(Path(bob["snapshot_path"]).exists())
        self.assertEqual(
            self.destination / "alice",
            Path(alice["backup_storage"])
        )
        self.assertEqual(
            self.destination / "bob",
            Path(bob["backup_storage"])
        )
        self.assertEqual(2, len(self.object_paths()))

    def test_first_backup_defers_classification_to_background(self):
        backup_manager.HISTORY_PATH = str(self.root / "config" / "backup_history.json")
        self.write_file("A.txt", "a")
        events = []

        def progress_callback(percent, message):
            if percent == 100:
                events.append("backup_complete")

        with patch("scanner.scanner.run_scanner") as run_scanner_mock:
            with patch(
                "backup.backup_manager.start_background_classification_scan"
            ) as background_scan_mock:
                background_scan_mock.side_effect = lambda: events.append(
                    "background_classification"
                )
                run_backup_job(
                    directories=[str(self.source)],
                    backup_destination=str(self.destination),
                    username="Alice",
                    user_role="operator",
                    company_id="default",
                    now=self.now,
                    run_scan_first=True,
                    progress_callback=progress_callback,
                )

        run_scanner_mock.assert_called_once()
        self.assertIs(
            False,
            run_scanner_mock.call_args.kwargs.get("classify_files")
        )
        background_scan_mock.assert_called_once()
        self.assertEqual(
            ["backup_complete", "background_classification"],
            events
        )

    def test_priority_backup_is_skipped_when_another_backup_is_running(self):
        acquired = backup_manager._BACKUP_EXECUTION_LOCK.acquire(blocking=False)
        self.addCleanup(
            lambda: backup_manager._BACKUP_EXECUTION_LOCK.release()
            if acquired and backup_manager._BACKUP_EXECUTION_LOCK.locked()
            else None
        )

        result = run_priority_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="sistema",
            user_role="system",
            run_scan_first=False,
        )

        self.assertTrue(result["skipped"])
        self.assertIn("Outro backup", result["reason"])

    def test_followup_backup_runs_full_scan_before_incremental_snapshot(self):
        backup_manager.HISTORY_PATH = str(self.root / "config" / "backup_history.json")
        self.write_file("A.txt", "a")

        run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Alice",
            user_role="operator",
            company_id="default",
            now=self.now,
            run_scan_first=False,
        )

        with patch("scanner.scanner.run_scanner") as run_scanner_mock:
            with patch(
                "backup.backup_manager.start_background_classification_scan"
            ) as background_scan_mock:
                run_backup_job(
                    directories=[str(self.source)],
                    backup_destination=str(self.destination),
                    username="Alice",
                    user_role="operator",
                    company_id="default",
                    now=self.now + timedelta(seconds=1),
                    run_scan_first=True,
                )

        run_scanner_mock.assert_called_once()
        self.assertIs(
            False,
            run_scanner_mock.call_args.kwargs.get("classify_files")
        )
        background_scan_mock.assert_called_once()

    def test_incremental_backup_stores_new_objects_in_worker_threads(self):
        first = self.write_file("A.txt", "a")
        second = self.write_file("B.txt", "b")
        manifest = self.manifest_for(first, second)
        worker_names = []
        both_workers_started = threading.Event()
        original_store = backup_manager.store_incremental_object

        def store_with_thread_tracking(*args, **kwargs):
            worker_names.append(threading.current_thread().name)

            if len(worker_names) >= 2:
                both_workers_started.set()
            else:
                both_workers_started.wait(timeout=0.5)

            return original_store(*args, **kwargs)

        with patch(
            "backup.backup_manager.store_incremental_object",
            side_effect=store_with_thread_tracking
        ):
            self.run_backup(manifest)

        self.assertGreaterEqual(len(set(worker_names)), 2)
        self.assertNotIn(threading.current_thread().name, worker_names)

    def test_backup_job_separates_snapshots_by_date(self):
        backup_manager.HISTORY_PATH = str(self.root / "config" / "backup_history.json")
        file_path = self.write_file("A.txt", "a")
        manifest = self.manifest_for(file_path)

        first = run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Alice",
            user_role="operator",
            company_id="default",
            now=self.now,
            run_scan_first=False,
        )
        file_path.write_text("a2", encoding="utf-8")
        second = run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Alice",
            user_role="operator",
            company_id="default",
            now=self.now + timedelta(days=1),
            run_scan_first=False,
        )

        self.assertEqual(1, len(manifest))
        self.assertIn("2026-05-08", first["snapshot_path"])
        self.assertIn("2026-05-09", second["snapshot_path"])
        self.assertTrue((self.destination / "alice" / "index.json").exists())

    def test_backup_job_history_comparison_is_scoped_by_user(self):
        backup_manager.HISTORY_PATH = str(self.root / "config" / "backup_history.json")
        file_path = self.write_file("A.txt", "a")

        alice_first = run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Alice",
            user_role="operator",
            company_id="default",
            now=self.now,
            run_scan_first=False,
        )
        bob_first = run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Bob",
            user_role="operator",
            company_id="default",
            now=self.now,
            run_scan_first=False,
        )
        alice_second = run_backup_job(
            directories=[str(self.source)],
            backup_destination=str(self.destination),
            username="Alice",
            user_role="operator",
            company_id="default",
            now=self.now + timedelta(seconds=1),
            run_scan_first=False,
        )

        self.assertTrue(file_path.exists())
        self.assertEqual(["adicionado"], [item["action"] for item in alice_first["file_changes"]])
        self.assertEqual(["adicionado"], [item["action"] for item in bob_first["file_changes"]])
        self.assertEqual([], alice_second["file_changes"])


if __name__ == "__main__":
    unittest.main()
