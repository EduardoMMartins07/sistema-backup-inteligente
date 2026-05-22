import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import auth.users as users
from auth.users import authenticate
from auth.users import change_user_password
from auth.users import create_user
from backup.backup_manager import create_encrypted_snapshot_archive
from backup.backup_manager import export_snapshot_to_zip
from backup.backup_manager import restore_snapshot
from backup.backup_manager import run_incremental_backup
from security import crypto_service


@unittest.skipUnless(
    crypto_service.is_crypto_available(),
    "cryptography nao esta instalada neste ambiente"
)
class EncryptionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.original_users_path = users.USERS_PATH
        users.USERS_PATH = str(self.root / "config" / "users.json")

    def tearDown(self):
        users.USERS_PATH = self.original_users_path
        self.tempdir.cleanup()

    def write_source(self, name, content):
        source_dir = self.root / "source"
        source_dir.mkdir(exist_ok=True)
        file_path = source_dir / name
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def manifest_for(self, *paths):
        source_dir = self.root / "source"
        return [
            (str(path), f"source/{path.relative_to(source_dir).as_posix()}")
            for path in paths
        ]

    def test_user_crypto_metadata_is_encrypted_and_password_change_preserves_master(self):
        created = create_user("Admin", "senha-segura", "admin", name="Admin")
        recovery_key = created.get("recovery_key")
        stored_users = json.loads(Path(users.USERS_PATH).read_text(encoding="utf-8"))
        stored_user = stored_users[0]

        self.assertTrue(recovery_key.startswith("RECOVERY-"))
        self.assertNotIn("_session_master_key", stored_user)
        self.assertNotIn("_recovery_key", stored_user)
        self.assertNotEqual("senha-segura", stored_user["password"])
        self.assertTrue(stored_user["encrypted_master_key"])
        self.assertTrue(stored_user["master_key_nonce"])

        session_before = authenticate("admin", "senha-segura")
        change_user_password("admin", "senha-segura", "nova-senha")
        self.assertIsNone(authenticate("admin", "senha-segura"))
        session_after = authenticate("admin", "nova-senha")

        self.assertEqual(
            session_before["session_master_key"],
            session_after["session_master_key"],
        )

    def test_incremental_backup_encrypts_objects_and_restores_with_session_key(self):
        create_user("Admin", "senha-segura", "admin", name="Admin")
        session = authenticate("admin", "senha-segura")
        source_file = self.write_source("A.txt", "conteudo secreto")
        destination = self.root / "backups"

        result = run_incremental_backup(
            directories=[str(source_file.parent)],
            backup_destination=str(destination),
            manifest=self.manifest_for(source_file),
            encryption_context={
                "master_key": session["session_master_key"],
                "user_id": session["username"],
                "company_id": session["company_id"],
            },
        )
        snapshot = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
        stored_object = Path(result["backup_storage"]) / snapshot["files"][0]["object_path"]
        legacy_storage = destination / "backup_storage"

        self.assertTrue(stored_object.exists())
        self.assertEqual("arquivos_relacionados", stored_object.parent.name)
        self.assertNotEqual(b"conteudo secreto", stored_object.read_bytes())
        self.assertEqual("AES-256-GCM", snapshot["encryption"]["algorithm"])
        self.assertTrue(snapshot["files"][0]["encryption"]["encrypted"])
        self.assertFalse(legacy_storage.exists())

        restore_destination = self.root / "restore"
        restored = restore_snapshot(
            result["snapshot_path"],
            str(restore_destination),
            user_master_key=session["session_master_key"],
        )

        self.assertEqual("restored", restored[0]["status"])
        self.assertEqual(
            "conteudo secreto",
            (restore_destination / "source" / "A.txt").read_text(encoding="utf-8"),
        )

        missing_key_restore = restore_snapshot(
            result["snapshot_path"],
            str(self.root / "restore_without_key"),
        )
        self.assertEqual("error", missing_key_restore[0]["status"])

    def test_encrypted_archive_is_zip_enc_and_plain_zip_is_removed(self):
        create_user("Admin", "senha-segura", "admin", name="Admin")
        session = authenticate("admin", "senha-segura")
        source_file = self.write_source("A.txt", "conteudo secreto")
        destination = self.root / "backups"
        result = run_incremental_backup(
            directories=[str(source_file.parent)],
            backup_destination=str(destination),
            manifest=self.manifest_for(source_file),
            encryption_context={
                "master_key": session["session_master_key"],
                "user_id": session["username"],
                "company_id": session["company_id"],
            },
        )
        encrypted_archive = create_encrypted_snapshot_archive(
            result["snapshot_path"],
            str(destination),
            session["session_master_key"],
            backup_name="manual",
            user_id=session["username"],
            company_id=session["company_id"],
        )
        encrypted_path = Path(encrypted_archive["encrypted_file_path"])

        self.assertTrue(encrypted_path.exists())
        self.assertTrue(str(encrypted_path).endswith(".zip.enc"))

        with self.assertRaises(zipfile.BadZipFile):
            zipfile.ZipFile(encrypted_path, "r")

        exported_zip = self.root / "exports" / "restaurado.zip"
        export_snapshot_to_zip(
            result["snapshot_path"],
            str(exported_zip),
            user_master_key=session["session_master_key"],
        )

        with zipfile.ZipFile(exported_zip, "r") as archive:
            self.assertEqual("conteudo secreto", archive.read("source/A.txt").decode("utf-8"))

    def test_encrypted_archive_uses_fast_zip_export_and_streaming_encryption(self):
        create_user("Admin", "senha-segura", "admin", name="Admin")
        session = authenticate("admin", "senha-segura")
        source_file = self.write_source("A.txt", "conteudo secreto")
        destination = self.root / "backups"
        result = run_incremental_backup(
            directories=[str(source_file.parent)],
            backup_destination=str(destination),
            manifest=self.manifest_for(source_file),
            encryption_context={
                "master_key": session["session_master_key"],
                "user_id": session["username"],
                "company_id": session["company_id"],
            },
        )
        observed = {}
        original_export = create_encrypted_snapshot_archive.__globals__[
            "export_snapshot_to_zip"
        ]
        original_stream = crypto_service.encrypt_file_streaming

        def capture_export(*args, **kwargs):
            observed["compression_method"] = kwargs.get("compression_method")
            return original_export(*args, **kwargs)

        def capture_stream(*args, **kwargs):
            observed["streaming_called"] = True
            return original_stream(*args, **kwargs)

        with patch(
            "backup.backup_manager.export_snapshot_to_zip",
            side_effect=capture_export,
        ):
            with patch(
                "security.crypto_service.encrypt_file_streaming",
                side_effect=capture_stream,
            ):
                encrypted_archive = create_encrypted_snapshot_archive(
                    result["snapshot_path"],
                    str(destination),
                    session["session_master_key"],
                    backup_name="manual",
                    user_id=session["username"],
                    company_id=session["company_id"],
                )

        self.assertEqual(zipfile.ZIP_STORED, observed["compression_method"])
        self.assertTrue(observed["streaming_called"])
        self.assertTrue(Path(encrypted_archive["encrypted_file_path"]).exists())

    def test_streaming_file_encryption_is_compatible_with_file_decryption(self):
        key = crypto_service.generate_key()
        source_path = self.root / "plain.bin"
        encrypted_path = self.root / "plain.bin.enc"
        restored_path = self.root / "plain.restored.bin"
        source_path.write_bytes((b"conteudo secreto" * 8192) + b"fim")

        encrypted = crypto_service.encrypt_file_streaming(
            str(source_path),
            str(encrypted_path),
            key,
            b"encrypted-backup-archive",
            chunk_size=1024,
        )
        crypto_service.decrypt_file(
            str(encrypted_path),
            str(restored_path),
            key,
            encrypted["file_nonce"],
            b"encrypted-backup-archive",
        )

        self.assertEqual(source_path.read_bytes(), restored_path.read_bytes())

    def test_export_uses_index_encryption_metadata_when_snapshot_entry_is_legacy(self):
        create_user("Admin", "senha-segura", "admin", name="Admin")
        session = authenticate("admin", "senha-segura")
        source_file = self.write_source("A.txt", "conteudo secreto")
        destination = self.root / "backups"
        result = run_incremental_backup(
            directories=[str(source_file.parent)],
            backup_destination=str(destination),
            manifest=self.manifest_for(source_file),
            encryption_context={
                "master_key": session["session_master_key"],
                "user_id": session["username"],
                "company_id": session["company_id"],
            },
        )
        snapshot_path = Path(result["snapshot_path"])
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["files"][0].pop("encryption")
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        exported_zip = self.root / "exports" / "restaurado_legacy.zip"
        export_result = export_snapshot_to_zip(
            result["snapshot_path"],
            str(exported_zip),
            user_master_key=session["session_master_key"],
        )

        self.assertEqual([], export_result["warnings"])
        with zipfile.ZipFile(exported_zip, "r") as archive:
            self.assertEqual("conteudo secreto", archive.read("source/A.txt").decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
