import json
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

        uploaded_keys = [key for _, key, _ in client.uploads]
        self.assertEqual("sincronizado", result["cloud_sync_status"])
        self.assertIn("cloud_snapshot_key", result)
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertTrue(any("/snapshots/" in key for key in uploaded_keys))
        self.assertTrue(any("/arquivos_relacionados/" in key for key in uploaded_keys))
        self.assertEqual("sincronizado", self.load_history()[-1]["cloud_sync_status"])

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

        self.assertEqual("falhou", result["cloud_sync_status"])
        self.assertEqual("AccessDenied", result["cloud_error_message"])
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertEqual("falhou", self.load_history()[-1]["cloud_sync_status"])

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
