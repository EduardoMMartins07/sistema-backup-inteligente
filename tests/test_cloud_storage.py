import json
import threading
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import cloud.aws_s3_service as cloud_service
from security import crypto_service


class FakeS3Client:

    def __init__(self, fail_upload=False):
        self.fail_upload = fail_upload
        self.uploads = []
        self.upload_configs = []
        self.downloads = []
        self.deleted = []
        self.objects = {}

    def head_bucket(self, Bucket):
        if Bucket == "missing":
            raise RuntimeError("NoSuchBucket")

    def put_object(self, Bucket, Key, Body):
        if self.fail_upload:
            raise RuntimeError("AccessDenied: secret-token")
        self.uploads.append((Bucket, Key, Body))
        self.objects[(Bucket, Key)] = Body

    def delete_object(self, Bucket, Key):
        self.deleted.append((Bucket, Key))

    def upload_file(self, Filename, Bucket, Key, Config=None):
        if self.fail_upload:
            raise RuntimeError("AccessDenied: secret-token")
        data = Path(Filename).read_bytes()
        self.uploads.append((Bucket, Key, Filename))
        self.upload_configs.append(Config)
        self.objects[(Bucket, Key)] = data

    def download_file(self, Bucket, Key, Filename):
        self.downloads.append((Bucket, Key, Filename))
        Path(Filename).parent.mkdir(parents=True, exist_ok=True)
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def list_objects_v2(self, Bucket, Prefix):
        keys = [
            key
            for bucket, key in self.objects
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": [{"Key": key} for key in keys]}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise RuntimeError("NoSuchKey")


class CloudStorageTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_paths = {
            "CLOUD_SETTINGS_PATH": cloud_service.CLOUD_SETTINGS_PATH,
            "CLOUD_SECRET_KEY_PATH": cloud_service.CLOUD_SECRET_KEY_PATH,
        }
        cloud_service.CLOUD_SETTINGS_PATH = str(self.root / "cloud_settings.json")
        cloud_service.CLOUD_SECRET_KEY_PATH = str(self.root / "cloud_secret.key")

    def tearDown(self):
        cloud_service.CLOUD_SETTINGS_PATH = self.original_paths["CLOUD_SETTINGS_PATH"]
        cloud_service.CLOUD_SECRET_KEY_PATH = self.original_paths["CLOUD_SECRET_KEY_PATH"]
        self.temp.cleanup()

    def write_backup_fixture(self):
        storage_root = self.root / "backups" / "default" / "dudu"
        day_root = storage_root / "2026-05-20"
        objects_dir = day_root / "arquivos_relacionados"
        snapshots_dir = day_root / "snapshots"
        objects_dir.mkdir(parents=True)
        snapshots_dir.mkdir(parents=True)
        object_path = objects_dir / "abc123"
        snapshot_path = snapshots_dir / "snapshot_2026-05-20_20-54-18.json"
        index_path = storage_root / "index.json"
        object_path.write_bytes(b"object-data")
        index_path.write_text("{}", encoding="utf-8")
        snapshot = {
            "snapshot_id": "snapshot_2026-05-20_20-54-18",
            "storage_root": str(storage_root),
            "files": [
                {
                    "archive_name": "source/A.txt",
                    "hash": "abc123",
                    "object_path": "2026-05-20/arquivos_relacionados/abc123",
                    "status": "stored_new_object",
                }
            ],
        }
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        return {
            "timestamp": "20/05/2026 20:54:18",
            "backup_path": str(snapshot_path),
            "snapshot_path": str(snapshot_path),
            "backup_storage": str(storage_root),
            "index_path": str(index_path),
            "user": "dudu",
            "company_id": "default",
            "storage_mode": "incremental",
            "file_snapshot": {
                "source/A.txt": {
                    "object_path": "2026-05-20/arquivos_relacionados/abc123",
                    "file_hash": "abc123",
                }
            },
        }

    def enabled_settings(self):
        return {
            "enabled": True,
            "bucket_name": "backup-bucket",
            "region": "us-east-1",
            "base_prefix": "backups",
            "access_key_id": "AKIA123456",
            "secret_access_key": "super-secret",
        }

    def test_build_s3_key_sanitizes_segments_and_keeps_expected_layout(self):
        key = cloud_service.build_s3_key(
            "../../empresa A",
            "user/25",
            "2026-05-20",
            "../snapshots/snapshot.json",
            base_prefix="/backups//"
        )

        self.assertEqual(
            "backups/empresa_A/user_25/2026-05-20/snapshots/snapshot.json",
            key
        )

    @unittest.skipUnless(
        crypto_service.is_crypto_available(),
        "cryptography nao esta instalada neste ambiente"
    )
    def test_settings_encrypt_secret_and_public_view_masks_it(self):
        cloud_service.save_cloud_settings(self.enabled_settings())

        raw_settings = json.loads(
            Path(cloud_service.CLOUD_SETTINGS_PATH).read_text(encoding="utf-8")
        )
        self.assertNotIn("super-secret", json.dumps(raw_settings))

        loaded = cloud_service.load_cloud_settings(include_secret=True)
        self.assertEqual("super-secret", loaded["secret_access_key"])

        public = cloud_service.get_public_cloud_settings()
        self.assertNotIn("secret_access_key", public)
        self.assertEqual("************", public["secret_access_key_masked"])

    @unittest.skipUnless(
        crypto_service.is_crypto_available(),
        "cryptography nao esta instalada neste ambiente"
    )
    def test_save_settings_preserves_existing_secret_when_field_is_blank(self):
        cloud_service.save_cloud_settings(self.enabled_settings())
        cloud_service.save_cloud_settings(
            {
                "enabled": True,
                "bucket_name": "other-bucket",
                "region": "us-west-2",
                "base_prefix": "prod",
                "access_key_id": "AKIA123456",
                "secret_access_key": "",
            }
        )

        loaded = cloud_service.load_cloud_settings(include_secret=True)
        self.assertEqual("super-secret", loaded["secret_access_key"])
        self.assertEqual("other-bucket", loaded["bucket_name"])

    def test_test_s3_connection_validates_bucket_upload_and_delete(self):
        client = FakeS3Client()
        result = cloud_service.test_s3_connection(
            settings=self.enabled_settings(),
            client=client,
            now=datetime(2026, 5, 20, 20, 54, 18),
        )

        self.assertTrue(result["success"])
        self.assertEqual("ok", result["status"])
        self.assertEqual(1, len(client.deleted))

    def test_normalized_runtime_settings_keep_secret_for_connection_test(self):
        settings = cloud_service.normalize_cloud_settings(self.enabled_settings())

        self.assertEqual("super-secret", settings["secret_access_key"])

    def test_test_s3_connection_returns_sanitized_failure(self):
        client = FakeS3Client(fail_upload=True)
        result = cloud_service.test_s3_connection(
            settings=self.enabled_settings(),
            client=client,
        )

        self.assertFalse(result["success"])
        self.assertEqual("falhou", result["status"])
        self.assertNotIn("secret-token", result["message"])

    def test_sync_backup_uploads_snapshot_objects_and_index(self):
        history_entry = self.write_backup_fixture()
        client = FakeS3Client()
        progress_events = []

        result = cloud_service.sync_backup_to_s3(
            history_entry,
            settings=self.enabled_settings(),
            client=client,
            progress_callback=lambda done, total, message: progress_events.append(
                (done, total, message)
            ),
        )

        uploaded_keys = [key for _, key, _ in client.uploads]
        self.assertEqual("sincronizado", result["cloud_sync_status"])
        self.assertIn(
            "backups/default/dudu/2026-05-20/snapshots/snapshot_2026-05-20_20-54-18.json",
            uploaded_keys,
        )
        self.assertIn(
            "backups/default/dudu/2026-05-20/arquivos_relacionados/abc123",
            uploaded_keys,
        )
        self.assertIn("backups/default/dudu/index.json", uploaded_keys)
        self.assertTrue(progress_events)
        self.assertEqual(3, progress_events[-1][0])
        self.assertEqual(3, progress_events[-1][1])
        self.assertIn("AWS S3", progress_events[-1][2])

    def test_sync_backup_uploads_only_new_incremental_objects(self):
        history_entry = self.write_backup_fixture()
        storage_root = Path(history_entry["backup_storage"])
        reused_object = storage_root / "2026-05-20" / "arquivos_relacionados" / "old456"
        reused_object.write_bytes(b"old-data")
        snapshot_path = Path(history_entry["snapshot_path"])
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["files"].append(
            {
                "archive_name": "source/B.txt",
                "hash": "old456",
                "object_path": "2026-05-20/arquivos_relacionados/old456",
                "status": "skipped_unchanged",
            }
        )
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        history_entry["file_snapshot"]["source/B.txt"] = {
            "object_path": "2026-05-20/arquivos_relacionados/old456",
            "file_hash": "old456",
            "status": "skipped_unchanged",
        }
        client = FakeS3Client()
        client.objects[
            (
                "backup-bucket",
                "backups/default/dudu/2026-05-20/arquivos_relacionados/old456",
            )
        ] = b"old-data"

        cloud_service.sync_backup_to_s3(
            history_entry,
            settings=self.enabled_settings(),
            client=client,
        )

        uploaded_keys = [key for _, key, _ in client.uploads]
        self.assertIn(
            "backups/default/dudu/2026-05-20/arquivos_relacionados/abc123",
            uploaded_keys,
        )
        self.assertNotIn(
            "backups/default/dudu/2026-05-20/arquivos_relacionados/old456",
            uploaded_keys,
        )

    def test_sync_backup_uploads_objects_in_worker_threads(self):
        history_entry = self.write_backup_fixture()
        storage_root = Path(history_entry["backup_storage"])
        second_object = storage_root / "2026-05-20" / "arquivos_relacionados" / "def456"
        second_object.write_bytes(b"second-object-data")
        snapshot_path = Path(history_entry["snapshot_path"])
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["files"].append(
            {
                "archive_name": "source/B.txt",
                "hash": "def456",
                "object_path": "2026-05-20/arquivos_relacionados/def456",
                "status": "stored_new_object",
            }
        )
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        client = FakeS3Client()
        worker_names = []
        both_workers_started = threading.Event()
        original_upload_file = cloud_service.upload_file

        def upload_with_thread_tracking(*args, **kwargs):
            worker_names.append(threading.current_thread().name)

            if len(worker_names) >= 2:
                both_workers_started.set()
            else:
                both_workers_started.wait(timeout=0.5)

            return original_upload_file(*args, **kwargs)

        original_worker_count = cloud_service.get_cloud_upload_worker_count
        cloud_service.get_cloud_upload_worker_count = lambda total_uploads: 2
        self.addCleanup(
            lambda: setattr(
                cloud_service,
                "get_cloud_upload_worker_count",
                original_worker_count,
            )
        )

        try:
            cloud_service.upload_file = upload_with_thread_tracking
            self.addCleanup(
                lambda: setattr(cloud_service, "upload_file", original_upload_file)
            )
            cloud_service.sync_backup_to_s3(
                history_entry,
                settings=self.enabled_settings(),
                client=client,
            )
        finally:
            cloud_service.upload_file = original_upload_file

        self.assertGreaterEqual(len(set(worker_names)), 2)
        self.assertNotIn(threading.current_thread().name, worker_names)

    def test_cloud_performance_settings_are_normalized(self):
        settings = cloud_service.normalize_cloud_settings(
            {
                **self.enabled_settings(),
                "cloud_upload_workers": "32",
                "cloud_max_pool_connections": "40",
                "multipart_threshold_mb": "12",
                "multipart_chunksize_mb": "16",
            }
        )

        self.assertEqual(32, settings["cloud_upload_workers"])
        self.assertEqual(40, settings["cloud_max_pool_connections"])
        self.assertEqual(12, settings["multipart_threshold_mb"])
        self.assertEqual(16, settings["multipart_chunksize_mb"])

    def test_sync_backup_uses_configurable_workers_and_transfer_config(self):
        history_entry = self.write_backup_fixture()
        client = FakeS3Client()
        settings = {
            **self.enabled_settings(),
            "cloud_upload_workers": 12,
            "multipart_threshold_mb": 5,
            "multipart_chunksize_mb": 7,
        }
        observed = {}

        def fake_worker_count(total_uploads, worker_settings=None):
            observed["worker_settings"] = worker_settings
            return 1

        transfer_config = object()

        with patch(
            "cloud.aws_s3_service.get_cloud_upload_worker_count",
            side_effect=fake_worker_count,
        ):
            with patch(
                "cloud.aws_s3_service.build_s3_transfer_config",
                return_value=transfer_config,
            ) as build_transfer:
                cloud_service.sync_backup_to_s3(
                    history_entry,
                    settings=settings,
                    client=client,
                )

        self.assertEqual(12, observed["worker_settings"]["cloud_upload_workers"])
        build_transfer.assert_called_once()
        self.assertTrue(client.uploads)
        self.assertTrue(all(config is transfer_config for config in client.upload_configs))

    def test_download_backup_restores_missing_snapshot_and_objects(self):
        history_entry = self.write_backup_fixture()
        client = FakeS3Client()
        sync_result = cloud_service.sync_backup_to_s3(
            history_entry,
            settings=self.enabled_settings(),
            client=client,
        )
        history_entry.update(sync_result)

        Path(history_entry["snapshot_path"]).unlink()
        object_path = Path(history_entry["backup_storage"]) / "2026-05-20" / "arquivos_relacionados" / "abc123"
        object_path.unlink()

        result = cloud_service.download_backup_from_s3(
            history_entry,
            settings=self.enabled_settings(),
            client=client,
        )

        self.assertEqual("sincronizado", result["cloud_sync_status"])
        self.assertTrue(Path(history_entry["snapshot_path"]).exists())
        self.assertTrue(object_path.exists())


if __name__ == "__main__":
    unittest.main()
