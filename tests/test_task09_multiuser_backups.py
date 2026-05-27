import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auth.local_context as local_context
import backup.backup_manager as backup_manager
from utils import user_data_paths

try:
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.database import init_db
except ModuleNotFoundError as error:
    raise unittest.SkipTest(f"Dependencias da API nao instaladas: {error}")


class Task09LocalUserDataTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_paths = {
            "APP_DATA_DIR": user_data_paths.APP_DATA_DIR,
            "COMPANIES_DIR": user_data_paths.COMPANIES_DIR,
            "MIGRATION_BACKUP_DIR": user_data_paths.MIGRATION_BACKUP_DIR,
            "LEGACY_CONFIG_DIR": user_data_paths.LEGACY_CONFIG_DIR,
            "LEGACY_CONFIG_PATH": user_data_paths.LEGACY_CONFIG_PATH,
            "LEGACY_HISTORY_PATH": user_data_paths.LEGACY_HISTORY_PATH,
            "LEGACY_SCHEDULE_PATH": user_data_paths.LEGACY_SCHEDULE_PATH,
            "LEGACY_PRIORITY_STATE_PATH": user_data_paths.LEGACY_PRIORITY_STATE_PATH,
            "LEGACY_MONITORED_FOLDERS_PATH": user_data_paths.LEGACY_MONITORED_FOLDERS_PATH,
            "LEGACY_BACKUP_STATE_PATH": user_data_paths.LEGACY_BACKUP_STATE_PATH,
            "LEGACY_TO_USER_FILES": user_data_paths.LEGACY_TO_USER_FILES,
            "SESSION_CONTEXT_PATH": local_context.SESSION_CONTEXT_PATH,
        }
        user_data_paths.APP_DATA_DIR = str(self.root / "app_data")
        user_data_paths.COMPANIES_DIR = str(self.root / "app_data" / "companies")
        user_data_paths.MIGRATION_BACKUP_DIR = str(self.root / "app_data" / "migration_backup")
        user_data_paths.LEGACY_CONFIG_DIR = str(self.root / "config")
        user_data_paths.LEGACY_CONFIG_PATH = str(self.root / "config" / "config.json")
        user_data_paths.LEGACY_HISTORY_PATH = str(self.root / "config" / "backup_history.json")
        user_data_paths.LEGACY_SCHEDULE_PATH = str(self.root / "config" / "backup_schedule.json")
        user_data_paths.LEGACY_PRIORITY_STATE_PATH = str(self.root / "config" / "priority_backup_state.json")
        user_data_paths.LEGACY_MONITORED_FOLDERS_PATH = str(self.root / "config" / "monitored_folders.json")
        user_data_paths.LEGACY_BACKUP_STATE_PATH = str(self.root / "config" / "backup_state.json")
        user_data_paths.LEGACY_TO_USER_FILES = {
            user_data_paths.LEGACY_CONFIG_PATH: "config.json",
            user_data_paths.LEGACY_HISTORY_PATH: "backup_history.json",
            user_data_paths.LEGACY_MONITORED_FOLDERS_PATH: "monitored_folders.json",
            user_data_paths.LEGACY_BACKUP_STATE_PATH: "backup_state.json",
            user_data_paths.LEGACY_PRIORITY_STATE_PATH: "backup_state.json",
            user_data_paths.LEGACY_SCHEDULE_PATH: "backup_schedule.json",
        }
        local_context.SESSION_CONTEXT_PATH = str(self.root / "config" / "desktop_session_context.json")
        local_context.clear_current_user()

    def tearDown(self):
        local_context.clear_current_user()

        for key, value in self.original_paths.items():
            setattr(
                user_data_paths if key != "SESSION_CONTEXT_PATH" else local_context,
                key,
                value,
            )

        self.temp.cleanup()

    def test_user_environment_creates_default_files_and_isolates_config(self):
        user_a = {
            "username": "ana@example.com",
            "role": "operator",
            "company_id": "company_a",
            "api_user_id": "user_a",
        }
        user_b = {
            "username": "bia@example.com",
            "role": "operator",
            "company_id": "company_a",
            "api_user_id": "user_b",
        }

        local_context.set_current_user(user_a)
        backup_manager.save_config({"directories": ["C:/Ana"]})
        user_a_dir = Path(user_data_paths.get_user_data_dir("company_a", "user_a"))

        self.assertTrue((user_a_dir / "config.json").exists())
        self.assertTrue((user_a_dir / "backup_history.json").exists())
        self.assertTrue((user_a_dir / "monitored_folders.json").exists())
        self.assertTrue((user_a_dir / "backup_state.json").exists())
        self.assertTrue((user_a_dir / "backup_schedule.json").exists())

        local_context.set_current_user(user_b)
        backup_manager.save_config({"directories": ["C:/Bia"]})

        self.assertEqual({"directories": ["C:/Bia"]}, backup_manager.load_config())

        local_context.set_current_user(user_a)
        self.assertEqual({"directories": ["C:/Ana"]}, backup_manager.load_config())

    def test_api_user_does_not_inherit_legacy_local_directories(self):
        os.makedirs(user_data_paths.LEGACY_CONFIG_DIR, exist_ok=True)

        with open(user_data_paths.LEGACY_CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump({"directories": ["C:/OutroUsuario"]}, file)

        local_context.set_current_user({
            "username": "dudu@example.com",
            "role": "operator",
            "company_id": "company_a",
            "api_user_id": "user_dudu",
            "auth_source": "api",
        })

        self.assertEqual({}, backup_manager.load_config())

        config_path = Path(user_data_paths.get_user_config_path("company_a", "user_dudu"))
        self.assertEqual({}, json.loads(config_path.read_text(encoding="utf-8")))


class Task09ApiBackupMetadataTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SMARTBACKUP_API_DB_PATH": os.environ.get("SMARTBACKUP_API_DB_PATH"),
            "SMARTBACKUP_API_STORAGE_ROOT": os.environ.get("SMARTBACKUP_API_STORAGE_ROOT"),
            "SMARTBACKUP_JWT_SECRET": os.environ.get("SMARTBACKUP_JWT_SECRET"),
            "JWT_SECRET": os.environ.get("JWT_SECRET"),
            "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
            "AWS_REGION": os.environ.get("AWS_REGION"),
            "AWS_S3_BUCKET": os.environ.get("AWS_S3_BUCKET"),
        }
        os.environ["SMARTBACKUP_API_DB_PATH"] = str(self.root / "api.sqlite3")
        os.environ["DATABASE_URL"] = f"sqlite:///{self.root / 'api.sqlite3'}"
        os.environ["SMARTBACKUP_API_STORAGE_ROOT"] = str(self.root / "api_storage")
        os.environ["SMARTBACKUP_JWT_SECRET"] = "test-secret"
        os.environ["JWT_SECRET"] = "test-secret"
        os.environ["AWS_ACCESS_KEY_ID"] = "test"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
        os.environ["AWS_REGION"] = "sa-east-1"
        os.environ["AWS_S3_BUCKET"] = "bucket-test"
        init_db(os.environ["SMARTBACKUP_API_DB_PATH"])
        self.client = TestClient(create_app())

    def tearDown(self):
        self.client.close()

        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        self.temp.cleanup()

    def signup(self, company, name, email):
        response = self.client.post(
            "/api/companies",
            json={
                "companyName": company,
                "name": name,
                "email": email,
                "password": "senha-admin",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        data = response.json()
        return data, {"Authorization": f"Bearer {data['token']}"}

    def create_operator(self, admin_headers, email):
        response = self.client.post(
            "/admin/users",
            headers=admin_headers,
            json={
                "name": "Operador",
                "email": email,
                "password": "senha-operador",
                "role": "OPERADOR",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        login = self.client.post(
            "/auth/login",
            json={"email": email, "password": "senha-operador"},
        )
        self.assertEqual(200, login.status_code, login.text)
        return response.json()["user"], {"Authorization": f"Bearer {login.json()['token']}"}

    def test_api_aliases_register_and_scope_backup_metadata(self):
        alpha, alpha_admin_headers = self.signup(
            "Empresa Alpha",
            "Admin Alpha",
            "admin.alpha@example.com",
        )
        beta, beta_admin_headers = self.signup(
            "Empresa Beta",
            "Admin Beta",
            "admin.beta@example.com",
        )
        operator, operator_headers = self.create_operator(
            alpha_admin_headers,
            "operador.alpha@example.com",
        )

        users = self.client.get(
            f"/api/companies/{alpha['company']['id']}/users",
            headers=alpha_admin_headers,
        )
        self.assertEqual(200, users.status_code, users.text)
        self.assertIn(operator["id"], [user["id"] for user in users.json()["users"]])

        forbidden_company = self.client.get(
            f"/api/companies/{beta['company']['id']}/users",
            headers=alpha_admin_headers,
        )
        self.assertEqual(403, forbidden_company.status_code)

        mismatch = self.client.post(
            "/api/backups",
            headers=operator_headers,
            json={
                "backup_id": "backup_intruso",
                "company_id": beta["company"]["id"],
                "backup_name": "Backup intruso",
            },
        )
        self.assertEqual(403, mismatch.status_code)

        created = self.client.post(
            "/api/backups",
            headers=operator_headers,
            json={
                "backup_id": "backup_task09_001",
                "company_id": alpha["company"]["id"],
                "backup_name": "Backup Task 09",
                "backup_type": "incremental",
                "status": "success",
                "priority": "high",
                "file_count": 7,
                "total_size_bytes": 4096,
                "storage_target": "s3",
                "remote_path": "s3://bucket/company/user/backup_task09_001/",
                "items": [
                    {
                        "name": "A.txt",
                        "archive_name": "docs/A.txt",
                        "size_bytes": 512,
                        "status": "stored_new_object",
                    }
                ],
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        self.assertEqual("SUCCESS", created.json()["backup"]["status"])

        mine = self.client.get("/api/me/backups", headers=operator_headers)
        self.assertEqual(["backup_task09_001"], [item["id"] for item in mine.json()["backups"]])

        company_backups = self.client.get(
            f"/api/companies/{alpha['company']['id']}/backups",
            headers=alpha_admin_headers,
        )
        self.assertEqual(["backup_task09_001"], [item["id"] for item in company_backups.json()["backups"]])

        blocked = self.client.get(
            f"/api/companies/{alpha['company']['id']}/backups",
            headers=beta_admin_headers,
        )
        self.assertEqual(403, blocked.status_code)

        detail = self.client.get("/api/backups/backup_task09_001", headers=operator_headers)
        self.assertEqual(200, detail.status_code, detail.text)
        self.assertEqual("Backup Task 09", detail.json()["backup"]["name"])
        self.assertEqual("A.txt", detail.json()["backup"]["metadata"]["items"][0]["name"])

        snapshots = self.client.get("/snapshots", headers=alpha_admin_headers)
        self.assertEqual(200, snapshots.status_code, snapshots.text)
        self.assertEqual([], snapshots.json()["snapshots"])

    def test_web_common_user_sees_personal_backups_page(self):
        alpha, alpha_admin_headers = self.signup(
            "Empresa Alpha",
            "Admin Alpha",
            "admin.alpha@example.com",
        )
        _, operator_headers = self.create_operator(
            alpha_admin_headers,
            "operador.alpha@example.com",
        )
        self.client.post(
            "/api/backups",
            headers=operator_headers,
            json={
                "backup_id": "backup_web_user",
                "company_id": alpha["company"]["id"],
                "backup_name": "Backup Web User",
                "status": "success",
            },
        )

        login = self.client.post(
            "/web/login",
            data={"email": "operador.alpha@example.com", "password": "senha-operador"},
            follow_redirects=False,
        )
        self.assertEqual(303, login.status_code, login.text)
        self.assertEqual("/web/my-backups", login.headers["location"])

        page = self.client.get("/web/my-backups")
        self.assertEqual(200, page.status_code, page.text)
        self.assertIn("Backup Web User", page.text)

        admin_only = self.client.get("/web/users")
        self.assertEqual(403, admin_only.status_code)

    def test_metadata_backup_uses_item_sizes_when_total_size_is_missing(self):
        alpha, alpha_admin_headers = self.signup(
            "Empresa Alpha",
            "Admin Alpha",
            "admin.alpha@example.com",
        )
        _, operator_headers = self.create_operator(
            alpha_admin_headers,
            "operador.alpha@example.com",
        )

        created = self.client.post(
            "/api/backups",
            headers=operator_headers,
            json={
                "backup_id": "backup_size_from_items",
                "company_id": alpha["company"]["id"],
                "backup_name": "Backup com tamanho pelos arquivos",
                "status": "success",
                "items": [
                    {"name": "A.txt", "archive_name": "A.txt", "size_bytes": 100},
                    {"name": "B.txt", "archive_name": "B.txt", "size": 50},
                ],
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        self.assertEqual(150, created.json()["backup"]["sizeBytes"])

        login = self.client.post(
            "/web/login",
            data={"email": "admin.alpha@example.com", "password": "senha-admin"},
            follow_redirects=False,
        )
        self.assertEqual(303, login.status_code, login.text)

        page = self.client.get("/web/snapshots")
        self.assertEqual(200, page.status_code, page.text)
        self.assertIn("Nenhum snapshot registrado.", page.text)

    def test_backup_download_endpoint_returns_presigned_url_for_scoped_backup(self):
        alpha, alpha_admin_headers = self.signup(
            "Empresa Alpha",
            "Admin Alpha",
            "admin.alpha@example.com",
        )
        _, operator_headers = self.create_operator(
            alpha_admin_headers,
            "operador.alpha@example.com",
        )
        self.client.post(
            "/api/backups",
            headers=operator_headers,
            json={
                "backup_id": "backup_download",
                "company_id": alpha["company"]["id"],
                "backup_name": "Backup Download",
                "status": "success",
                "remote_path": "s3://bucket-test/backups/company/user/backup.zip",
            },
        )

        class FakeStorage:
            def create_presigned_download_url(self, key):
                return {
                    "url": f"https://example.test/{key}",
                    "method": "GET",
                    "bucket": "bucket-test",
                    "key": key,
                    "expiresIn": 300,
                }

        with patch("api.app.S3StorageService", return_value=FakeStorage()):
            response = self.client.get(
                "/api/backups/backup_download/download",
                headers=operator_headers,
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("backups/company/user/backup.zip", response.json()["s3Key"])
        self.assertEqual(
            "https://example.test/backups/company/user/backup.zip",
            response.json()["download"]["url"],
        )


if __name__ == "__main__":
    unittest.main()
