import json
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
        self.original_api_base_url = os.environ.get("API_BASE_URL")
        self.original_api_url = os.environ.get("API_URL")
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

        if self.original_api_base_url is None:
            os.environ.pop("API_BASE_URL", None)
        else:
            os.environ["API_BASE_URL"] = self.original_api_base_url

        if self.original_api_url is None:
            os.environ.pop("API_URL", None)
        else:
            os.environ["API_URL"] = self.original_api_url

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

    def test_desktop_admin_lists_local_api_company_users_without_http_base_url(self):
        os.environ.pop("API_BASE_URL", None)
        os.environ.pop("API_URL", None)
        db = connect(os.environ["SMARTBACKUP_API_DB_PATH"])

        try:
            company = create_company(db, "Empresa Alpha")
            admin = create_user(
                db,
                company["id"],
                "Djogo",
                "djogo@gmail.com",
                "senha-admin",
                "ADMIN_EMPRESA",
            )
            create_user(
                db,
                company["id"],
                "Dudu",
                "dudu@gmail.com",
                "senha-dudu",
                "OPERADOR",
            )
            db.commit()
        finally:
            db.close()

        session = desktop_users.public_api_user(admin)
        users = desktop_users.list_public_users(current_user=session)
        usernames = [user["username"] for user in users]

        self.assertEqual(["djogo@gmail.com", "dudu@gmail.com"], usernames)
        self.assertEqual(["admin", "operator"], [user["role"] for user in users])

    def test_desktop_prefers_api_role_over_stale_cached_role(self):
        os.environ.pop("API_BASE_URL", None)
        os.environ.pop("API_URL", None)
        db = connect(os.environ["SMARTBACKUP_API_DB_PATH"])

        try:
            company = create_company(db, "Empresa Alpha")
            user = create_user(
                db,
                company["id"],
                "Dudu",
                "dudu@gmail.com",
                "senha-dudu",
                "ADMIN_EMPRESA",
            )
            db.commit()
        finally:
            db.close()

        with open(desktop_users.USERS_PATH, "w", encoding="utf-8") as file:
            json.dump(
                [
                    {
                        "username": "dudu@gmail.com",
                        "name": "Dudu",
                        "role": "operator",
                        "company_id": company["id"],
                        "password": desktop_users.hash_password("senha-dudu"),
                        "created_at": "2026-06-01T19:00:00",
                        "updated_at": "2026-06-01T19:00:00",
                        "api_user_id": user["id"],
                        "api_company_id": company["id"],
                        "api_sync_status": "synced",
                        "auth_source": "api",
                    }
                ],
                file,
                indent=4,
            )

        session = desktop_users.authenticate("dudu@gmail.com", "senha-dudu")

        self.assertIsNotNone(session)
        self.assertEqual("admin", session["role"])
        self.assertEqual("api", session["auth_source"])

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
            "file_snapshot": {
                "docs/A.txt": {
                    "name": "A.txt",
                    "archive_name": "docs/A.txt",
                    "size_bytes": 128,
                    "status": "stored_new_object",
                }
            },
        }

        self.assertTrue(sync_history_entry(entry))

        db = connect(os.environ["SMARTBACKUP_API_DB_PATH"])

        try:
            backup = db.execute(
                "SELECT * FROM backups WHERE company_id = ?",
                (company["id"],),
            ).fetchone()
            self.assertIsNotNone(backup)
            self.assertNotIn("snapshot", backup["id"])
            self.assertEqual("Backup pelo desktop", backup["name"])
            self.assertEqual("SUCCESS", backup["status"])
            self.assertEqual(12, backup["file_count"])
            self.assertEqual("backups/company/user/device/folder/backup/snapshot.json", backup["s3_key"])
            metadata = json.loads(backup["metadata_json"])
            self.assertEqual("A.txt", metadata["items"][0]["name"])

            snapshot_count = db.execute(
                "SELECT COUNT(*) AS total FROM snapshots WHERE backup_id = ?",
                (backup["id"],),
            ).fetchone()["total"]
            self.assertEqual(0, snapshot_count)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
