import os
import tempfile
import unittest
from pathlib import Path

import auth.users as desktop_users
from api.database import connect, init_db
from api.local_history_sync import sync_history_entry
from api.services import create_company, create_user


class DesktopLoginApiUsersTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_users_path = desktop_users.USERS_PATH
        self.original_database_url = os.environ.get("DATABASE_URL")
        self.original_db_path = os.environ.get("SMARTBACKUP_API_DB_PATH")
        self.original_jwt_secret = os.environ.get("SMARTBACKUP_JWT_SECRET")
        desktop_users.USERS_PATH = str(self.root / "users.json")
        os.environ["SMARTBACKUP_API_DB_PATH"] = str(self.root / "api.sqlite3")
        os.environ["DATABASE_URL"] = f"sqlite:///{self.root / 'api.sqlite3'}"
        os.environ["SMARTBACKUP_JWT_SECRET"] = "test-secret"
        init_db(os.environ["SMARTBACKUP_API_DB_PATH"])

    def tearDown(self):
        desktop_users.USERS_PATH = self.original_users_path

        if self.original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self.original_database_url

        if self.original_db_path is None:
            os.environ.pop("SMARTBACKUP_API_DB_PATH", None)
        else:
            os.environ["SMARTBACKUP_API_DB_PATH"] = self.original_db_path

        if self.original_jwt_secret is None:
            os.environ.pop("SMARTBACKUP_JWT_SECRET", None)
        else:
            os.environ["SMARTBACKUP_JWT_SECRET"] = self.original_jwt_secret

        self.temp.cleanup()

    def test_desktop_authenticates_active_api_user_by_email(self):
        db = connect(os.environ["SMARTBACKUP_API_DB_PATH"])

        try:
            company = create_company(db, "Empresa Alpha")
            create_user(
                db,
                company["id"],
                "Operador Web",
                "operador.web@example.com",
                "senha-web",
                "OPERADOR",
            )
            db.commit()
        finally:
            db.close()

        self.assertTrue(desktop_users.users_exist())

        session = desktop_users.authenticate(
            "operador.web@example.com",
            "senha-web",
        )

        self.assertIsNotNone(session)
        self.assertEqual("operador.web@example.com", session["username"])
        self.assertEqual("operator", session["role"])
        self.assertEqual(company["id"], session["company_id"])
        self.assertEqual("api", session["auth_source"])
        self.assertTrue(session.get("auth_token"))

    def test_local_history_entry_syncs_to_api_backup_dashboard_data(self):
        db = connect(os.environ["SMARTBACKUP_API_DB_PATH"])

        try:
            company = create_company(db, "Empresa Alpha")
            user = create_user(
                db,
                company["id"],
                "Operador Web",
                "operador.web@example.com",
                "senha-web",
                "OPERADOR",
            )
            db.commit()
        finally:
            db.close()

        entry = {
            "snapshot_id": "snapshot_2026-05-23_18-30-00",
            "snapshot_path": "C:/Backups/snapshot_2026-05-23_18-30-00.json",
            "backup_path": "C:/Backups/snapshot_2026-05-23_18-30-00.json",
            "backup_name": "Backup pelo desktop",
            "backup_base_destination": "C:/Backups",
            "started_at": "2026-05-23T18:29:50",
            "finished_at": "2026-05-23T18:30:00",
            "status": "completed",
            "storage_mode": "incremental",
            "history_group_type": "full",
            "total_files": 12,
            "compacted_size_bytes": 2048,
            "trigger": "manual",
            "user": user["email"],
            "company_id": company["id"],
            "cloud_sync_status": "sincronizado",
            "cloud_snapshot_key": "backups/company/user/device/folder/backup/snapshot.json",
        }

        self.assertTrue(sync_history_entry(entry))

        db = connect(os.environ["SMARTBACKUP_API_DB_PATH"])

        try:
            backup = db.execute(
                "SELECT * FROM backups WHERE company_id = ?",
                (company["id"],),
            ).fetchone()
            self.assertIsNotNone(backup)
            self.assertEqual("Backup pelo desktop", backup["name"])
            self.assertEqual("SUCCESS", backup["status"])
            self.assertEqual(12, backup["file_count"])
            self.assertEqual("backups/company/user/device/folder/backup/snapshot.json", backup["s3_key"])

            snapshot_count = db.execute(
                "SELECT COUNT(*) AS total FROM snapshots WHERE backup_id = ?",
                (backup["id"],),
            ).fetchone()["total"]
            self.assertEqual(1, snapshot_count)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
