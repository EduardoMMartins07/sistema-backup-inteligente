import tempfile
import unittest
from pathlib import Path

from interface.gui import BACKUP_STATUS_IN_BACKUP
from interface.gui import BACKUP_STATUS_PENDING
from interface.gui import BACKUP_STATUS_PENDING_DELETE
from interface.gui import build_file_status_rows


class FileBackupStatusTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_path(self, name):
        return str(self.root / name)

    def rows_by_name(self, rows):
        return {row["name"]: row for row in rows}

    def test_status_rows_compare_dataset_with_latest_snapshot(self):
        same_path = self.make_path("same.txt")
        changed_path = self.make_path("changed.txt")
        new_path = self.make_path("new.txt")
        deleted_path = self.make_path("deleted.txt")
        history = [
            {
                "timestamp": "09/05/2026 17:13:35",
                "backup_file": "snapshot_2026-05-09_17-13-35.json",
                "file_snapshot": {
                    "root/same.txt": {
                        "name": "same.txt",
                        "source_path": same_path,
                        "archive_name": "root/same.txt",
                        "file_hash": "hash-same",
                        "size_bytes": 1024,
                        "modified_at": "2026-05-09T17:00:00",
                    },
                    "root/changed.txt": {
                        "name": "changed.txt",
                        "source_path": changed_path,
                        "archive_name": "root/changed.txt",
                        "file_hash": "old-hash",
                        "size_bytes": 2048,
                        "modified_at": "2026-05-09T17:00:00",
                    },
                    "root/deleted.txt": {
                        "name": "deleted.txt",
                        "source_path": deleted_path,
                        "archive_name": "root/deleted.txt",
                        "file_hash": "deleted-hash",
                        "size_bytes": 3072,
                        "modified_at": "2026-05-09T17:00:00",
                    },
                },
            }
        ]
        dataset_rows = [
            {
                "name": "same.txt",
                "extension": "txt",
                "source_path": same_path,
                "archive_name": "root\\same.txt",
                "size_kb": "1",
                "days_since_modified": "0",
                "added_to_backup_at": "09/05/2026 17:20:19",
                "file_hash": "hash-same",
                "priority": "media",
                "priority_score": "55",
            },
            {
                "name": "changed.txt",
                "extension": "txt",
                "source_path": changed_path,
                "archive_name": "root/changed.txt",
                "size_kb": "2",
                "days_since_modified": "0",
                "file_hash": "new-hash",
                "priority": "alta",
                "priority_score": "90",
            },
            {
                "name": "new.txt",
                "extension": "txt",
                "source_path": new_path,
                "archive_name": "root/new.txt",
                "size_kb": "3",
                "days_since_modified": "0",
                "file_hash": "brand-new",
                "priority": "baixa",
                "priority_score": "20",
            },
        ]

        rows = self.rows_by_name(build_file_status_rows(dataset_rows, history))

        self.assertEqual(BACKUP_STATUS_IN_BACKUP, rows["same.txt"]["backup_status"])
        self.assertEqual(BACKUP_STATUS_PENDING, rows["changed.txt"]["backup_status"])
        self.assertEqual(BACKUP_STATUS_PENDING, rows["new.txt"]["backup_status"])
        self.assertEqual(
            BACKUP_STATUS_PENDING_DELETE,
            rows["deleted.txt"]["backup_status"]
        )
        self.assertEqual(
            "09/05/2026 17:13:35",
            rows["same.txt"]["added_to_backup_at"]
        )
        self.assertEqual(
            "snapshot_2026-05-09_17-13-35.json",
            rows["deleted.txt"]["added_in_backup"]
        )

    def test_status_rows_without_history_marks_current_files_pending(self):
        current_path = self.make_path("current.txt")
        rows = build_file_status_rows(
            [
                {
                    "name": "current.txt",
                    "extension": "txt",
                    "source_path": current_path,
                    "archive_name": "root/current.txt",
                    "size_kb": "1",
                    "days_since_modified": "0",
                    "file_hash": "hash",
                }
            ],
            []
        )

        self.assertEqual(1, len(rows))
        self.assertEqual(BACKUP_STATUS_PENDING, rows[0]["backup_status"])
        self.assertEqual("-", rows[0]["added_to_backup_at"])
        self.assertEqual("-", rows[0]["added_in_backup"])


if __name__ == "__main__":
    unittest.main()
