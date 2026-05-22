import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup.backup_manager as backup_manager
import cloud.aws_s3_service as cloud_service
from backup.backup_manager import export_snapshot_to_zip
from backup.backup_manager import run_backup_job
from tests.test_cloud_storage import FakeS3Client


class CloudBackupIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "backups"
        self.config_path = self.root / "config" / "config.json"
        self.history_path = self.root / "config" / "backup_history.json"
        self.source.mkdir()
        self.destination.mkdir()
        self.config_path.parent.mkdir()
        (self.source / "A.txt").write_text("conteudo", encoding="utf-8")
        self.config_path.write_text(
            json.dumps(
                {
                    "directories": [str(self.source)],
                    "backup_destination": str(self.destination),
                }
            ),
            encoding="utf-8"
        )
        self.history_path.write_text("[]", encoding="utf-8")
        self.original_paths = {
            "CONFIG_PATH": backup_manager.CONFIG_PATH,
            "HISTORY_PATH": backup_manager.HISTORY_PATH,
        }
        backup_manager.CONFIG_PATH = str(self.config_path)
        backup_manager.HISTORY_PATH = str(self.history_path)

    def tearDown(self):
        backup_manager.CONFIG_PATH = self.original_paths["CONFIG_PATH"]
        backup_manager.HISTORY_PATH = self.original_paths["HISTORY_PATH"]
        self.temp.cleanup()

    def cloud_settings(self):
        return {
            "enabled": True,
            "bucket_name": "backup-bucket",
            "region": "us-east-1",
            "base_prefix": "backups",
            "access_key_id": "AKIA123456",
            "secret_access_key": "secret",
        }

    def load_history(self):
        return json.loads(self.history_path.read_text(encoding="utf-8"))

    def wait_for_cloud_status(self, expected_status, attempts=40):
        for _ in range(attempts):
            history = self.load_history()
            if history and history[-1].get("cloud_sync_status") == expected_status:
                return history[-1]
            time.sleep(0.05)

        return self.load_history()[-1]

    def test_manual_backup_syncs_incremental_files_to_s3_and_history(self):
        client = FakeS3Client()

        with patch.object(
            cloud_service,
            "load_cloud_settings",
            return_value=self.cloud_settings()
        ):
            with patch.object(
                cloud_service,
                "create_s3_client",
                return_value=client
            ):
                result = run_backup_job(
                    username="dudu",
                    user_role="operator",
                    company_id="default",
                    run_scan_first=False,
                )
                history_entry = self.wait_for_cloud_status("sincronizado")

        uploaded_keys = [key for _, key, _ in client.uploads]
        self.assertEqual("sincronizando", result["cloud_sync_status"])
        self.assertIn("cloud_snapshot_key", result)
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertTrue(any("/snapshots/" in key for key in uploaded_keys))
        self.assertTrue(any("/arquivos_relacionados/" in key for key in uploaded_keys))
        self.assertEqual("sincronizado", history_entry["cloud_sync_status"])

    def test_manual_backup_returns_with_cloud_syncing_and_starts_background_sync(self):
        with patch.object(
            cloud_service,
            "load_cloud_settings",
            return_value=self.cloud_settings()
        ):
            with patch.object(
                backup_manager,
                "start_cloud_sync_background",
                return_value=None
            ) as start_sync:
                result = run_backup_job(
                    username="dudu",
                    user_role="operator",
                    company_id="default",
                    run_scan_first=False,
                )

        self.assertEqual("sincronizando", result["cloud_sync_status"])
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertEqual("sincronizando", self.load_history()[-1]["cloud_sync_status"])
        start_sync.assert_called_once()

    def test_cloud_disabled_keeps_backup_local_without_background_sync(self):
        disabled_settings = {
            **self.cloud_settings(),
            "enabled": False,
        }

        with patch.object(
            cloud_service,
            "load_cloud_settings",
            return_value=disabled_settings
        ):
            with patch.object(
                backup_manager,
                "start_cloud_sync_background",
                return_value=None
            ) as start_sync:
                result = run_backup_job(
                    username="dudu",
                    user_role="operator",
                    company_id="default",
                    run_scan_first=False,
                )

        self.assertEqual("desativado", result["cloud_sync_status"])
        self.assertEqual("desativado", self.load_history()[-1]["cloud_sync_status"])
        start_sync.assert_not_called()

    def test_background_cloud_sync_updates_history_after_success(self):
        history_entry = {
            "timestamp": "21/05/2026 18:09:46",
            "backup_path": str(self.root / "snapshot.json"),
            "snapshot_path": str(self.root / "snapshot.json"),
            "cloud_sync_status": "sincronizando",
        }
        self.history_path.write_text(json.dumps([history_entry]), encoding="utf-8")
        sync_result = {
            "cloud_provider": "AWS S3",
            "cloud_bucket": "backup-bucket",
            "cloud_snapshot_key": "backups/default/dudu/snapshot.json",
            "cloud_storage_prefix": "backups/default/dudu/2026-05-21/",
            "cloud_sync_status": "sincronizado",
            "cloud_synced_at": "2026-05-21T18:10:00",
            "cloud_error_message": "",
        }

        with patch.object(
            backup_manager,
            "sync_history_entry_to_cloud",
            return_value=sync_result
        ):
            thread = backup_manager.start_cloud_sync_background(history_entry)
            thread.join(timeout=2)

        updated_entry = self.load_history()[-1]
        self.assertEqual("sincronizado", updated_entry["cloud_sync_status"])
        self.assertEqual("backups/default/dudu/snapshot.json", updated_entry["cloud_snapshot_key"])

    def test_background_cloud_sync_publishes_upload_progress(self):
        history_entry = {
            "timestamp": "21/05/2026 18:09:46",
            "backup_path": str(self.root / "snapshot.json"),
            "snapshot_path": str(self.root / "snapshot.json"),
            "cloud_sync_status": "sincronizando",
        }
        self.history_path.write_text(json.dumps([history_entry]), encoding="utf-8")
        sync_result = {
            "cloud_provider": "AWS S3",
            "cloud_bucket": "backup-bucket",
            "cloud_snapshot_key": "backups/default/dudu/snapshot.json",
            "cloud_storage_prefix": "backups/default/dudu/2026-05-21/",
            "cloud_sync_status": "sincronizado",
            "cloud_synced_at": "2026-05-21T18:10:00",
            "cloud_error_message": "",
        }

        def sync_with_progress(_entry, progress_callback=None):
            progress_callback(1, 3, "Enviando para AWS S3: 1/3")
            progress_callback(3, 3, "Enviando para AWS S3: 3/3")
            return sync_result

        with patch.object(
            backup_manager,
            "sync_history_entry_to_cloud",
            side_effect=sync_with_progress
        ):
            thread = backup_manager.start_cloud_sync_background(history_entry)
            thread.join(timeout=2)

        progress = backup_manager.get_cloud_sync_progress(history_entry["snapshot_path"])
        self.assertEqual("sincronizado", progress["status"])
        self.assertEqual(3, progress["processed"])
        self.assertEqual(3, progress["total"])
        self.assertIn("AWS", progress["message"])

    def test_resume_pending_cloud_syncs_restarts_syncing_entries(self):
        history_entry = {
            "timestamp": "21/05/2026 18:09:46",
            "backup_path": str(self.root / "snapshot.json"),
            "snapshot_path": str(self.root / "snapshot.json"),
            "cloud_sync_status": "sincronizando",
        }
        self.history_path.write_text(json.dumps([history_entry]), encoding="utf-8")

        with patch.object(
            backup_manager,
            "start_cloud_sync_background",
            return_value=None
        ) as start_sync:
            resumed = backup_manager.resume_pending_cloud_syncs()

        self.assertEqual([None], resumed)
        start_sync.assert_called_once()

    def test_cloud_upload_failure_keeps_local_backup_and_records_failure(self):
        client = FakeS3Client(fail_upload=True)

        with patch.object(
            cloud_service,
            "load_cloud_settings",
            return_value=self.cloud_settings()
        ):
            with patch.object(
                cloud_service,
                "create_s3_client",
                return_value=client
            ):
                result = run_backup_job(
                    username="dudu",
                    user_role="operator",
                    company_id="default",
                    run_scan_first=False,
                )
                history_entry = self.wait_for_cloud_status("falhou")

        self.assertEqual("sincronizando", result["cloud_sync_status"])
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertEqual("falhou", history_entry["cloud_sync_status"])
        self.assertEqual("AccessDenied", history_entry["cloud_error_message"])

    def test_export_downloads_missing_incremental_files_from_s3(self):
        client = FakeS3Client()

        with patch.object(
            cloud_service,
            "load_cloud_settings",
            return_value=self.cloud_settings()
        ):
            with patch.object(
                cloud_service,
                "create_s3_client",
                return_value=client
            ):
                result = run_backup_job(
                    username="dudu",
                    user_role="operator",
                    company_id="default",
                    run_scan_first=False,
                )
                self.wait_for_cloud_status("sincronizado")

                file_data = next(iter(result["file_snapshot"].values()))
                object_path = Path(result["backup_storage"]) / file_data["object_path"]
                Path(result["snapshot_path"]).unlink()
                object_path.unlink()

                export_result = export_snapshot_to_zip(
                    result["snapshot_path"],
                    str(self.root / "exportado.zip"),
                )

        self.assertEqual(1, export_result["files_exported"])
        self.assertTrue(Path(result["snapshot_path"]).exists())
        self.assertTrue(object_path.exists())


if __name__ == "__main__":
    unittest.main()
