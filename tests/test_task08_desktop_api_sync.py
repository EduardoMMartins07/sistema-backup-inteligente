import os
import tempfile
import unittest
from pathlib import Path

import auth.users as desktop_users

try:
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.database import init_db
except ModuleNotFoundError as error:
    raise unittest.SkipTest(f"Dependencias da API nao instaladas: {error}")


class Task08DesktopApiSyncTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SMARTBACKUP_API_DB_PATH": os.environ.get("SMARTBACKUP_API_DB_PATH"),
            "SMARTBACKUP_JWT_SECRET": os.environ.get("SMARTBACKUP_JWT_SECRET"),
            "JWT_SECRET": os.environ.get("JWT_SECRET"),
            "API_BASE_URL": os.environ.get("API_BASE_URL"),
            "API_URL": os.environ.get("API_URL"),
        }
        self.original_users_path = desktop_users.USERS_PATH
        desktop_users.USERS_PATH = str(self.root / "users.json")
        os.environ["SMARTBACKUP_API_DB_PATH"] = str(self.root / "api.sqlite3")
        os.environ["DATABASE_URL"] = f"sqlite:///{self.root / 'api.sqlite3'}"
        os.environ["SMARTBACKUP_JWT_SECRET"] = "test-secret"
        os.environ["JWT_SECRET"] = "test-secret"
        os.environ.pop("API_BASE_URL", None)
        os.environ.pop("API_URL", None)
        init_db(os.environ["SMARTBACKUP_API_DB_PATH"])
        self.client = TestClient(create_app())

    def tearDown(self):
        self.client.close()
        desktop_users.USERS_PATH = self.original_users_path

        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        self.temp.cleanup()

    def test_public_company_signup_creates_isolated_admins(self):
        alpha = self.client.post(
            "/api/companies",
            json={
                "companyName": "Empresa Alpha",
                "name": "Admin Alpha",
                "email": "admin.alpha@example.com",
                "password": "senha-alpha",
            },
        )
        beta = self.client.post(
            "/api/companies",
            json={
                "companyName": "Empresa Beta",
                "name": "Admin Beta",
                "email": "admin.beta@example.com",
                "password": "senha-beta",
            },
        )

        self.assertEqual(200, alpha.status_code, alpha.text)
        self.assertEqual(200, beta.status_code, beta.text)
        self.assertNotEqual(
            alpha.json()["company"]["id"],
            beta.json()["company"]["id"],
        )
        self.assertEqual("ADMIN_EMPRESA", alpha.json()["user"]["role"])
        self.assertIn("token", alpha.json())

    def test_desktop_config_cache_round_trips_by_authenticated_company(self):
        signup = self.client.post(
            "/api/companies",
            json={
                "companyName": "Empresa Alpha",
                "name": "Admin Alpha",
                "email": "admin.alpha@example.com",
                "password": "senha-alpha",
            },
        )
        headers = {"Authorization": f"Bearer {signup.json()['token']}"}
        payload = {
            "config": {
                "directories": ["C:/Projetos"],
                "backup_destination": "D:/Backups",
                "priority_backup_policy_enabled": True,
            },
            "history": [
                {
                    "snapshot_id": "snapshot_01",
                    "backup_name": "Backup desktop",
                    "company_id": signup.json()["company"]["id"],
                    "user": "admin.alpha@example.com",
                }
            ],
        }

        saved = self.client.put("/api/config/desktop", headers=headers, json=payload)
        loaded = self.client.get("/api/config/desktop", headers=headers)

        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(200, loaded.status_code, loaded.text)
        self.assertEqual(payload["config"], loaded.json()["config"])
        self.assertEqual(payload["history"], loaded.json()["history"])

    def test_desktop_user_created_offline_starts_pending_api_sync(self):
        user = desktop_users.create_user(
            "operador.local@example.com",
            "senha-local",
            "operator",
            name="Operador Local",
            company_id="company_local",
            api_sync_status="pending",
        )

        self.assertEqual("pending", user["api_sync_status"])
        self.assertEqual("company_local", user["company_id"])

    def test_pending_desktop_user_syncs_with_api_client(self):
        desktop_users.create_user(
            "operador.local@example.com",
            "senha-local",
            "operator",
            name="Operador Local",
            company_id="company_local",
            api_sync_status="pending",
        )

        def create_remote_user(user, password):
            self.assertEqual("operador.local@example.com", user["username"])
            self.assertEqual("senha-local", password)
            return {
                "id": "user_api_123",
                "companyId": "company_api_123",
            }

        synced = desktop_users.sync_pending_api_users(create_remote_user)
        [user] = desktop_users.list_public_users()

        self.assertEqual(1, synced)
        self.assertEqual("synced", user["api_sync_status"])
        self.assertEqual("user_api_123", user["api_user_id"])
        self.assertEqual("company_api_123", user["company_id"])

    def test_desktop_authenticate_prefers_http_api_when_configured(self):
        os.environ["API_BASE_URL"] = "https://api.example.test"

        def fake_login(username, password):
            self.assertEqual("operador.web@example.com", username)
            self.assertEqual("senha-web", password)
            return {
                "username": username,
                "name": "Operador Web",
                "role": "operator",
                "company_id": "company_api_123",
                "api_user_id": "user_api_123",
                "api_company_id": "company_api_123",
                "api_sync_status": "synced",
                "auth_source": "api",
                "auth_token": "token-api",
            }

        desktop_users.API_LOGIN_CLIENT = fake_login

        try:
            session = desktop_users.authenticate(
                "operador.web@example.com",
                "senha-web",
            )
        finally:
            desktop_users.API_LOGIN_CLIENT = None

        self.assertEqual("api", session["auth_source"])
        self.assertEqual("token-api", session["auth_token"])
        self.assertEqual("company_api_123", session["company_id"])

    def test_api_client_loads_env_file_before_checking_configuration(self):
        from auth import api_client
        from unittest.mock import patch

        os.environ.pop("API_BASE_URL", None)
        os.environ.pop("API_URL", None)

        def load_env():
            os.environ["API_BASE_URL"] = "https://api.example.test"

        with patch("api.config.load_env_file", side_effect=load_env):
            self.assertEqual(
                "https://api.example.test",
                api_client.get_api_base_url(),
            )

    def test_desktop_user_list_merges_api_company_users_with_local_cache(self):
        desktop_users.create_user(
            "admin.local@example.com",
            "senha-local",
            "admin",
            name="Admin Local",
            company_id="company_api_123",
            api_sync_status="local",
        )
        current_user = {
            "auth_token": "token-api",
            "company_id": "company_api_123",
        }

        def fake_remote_users(token):
            self.assertEqual("token-api", token)
            return [
                {
                    "id": "user_api_1",
                    "email": "admin.web@example.com",
                    "name": "Admin Web",
                    "role": "ADMIN_EMPRESA",
                    "companyId": "company_api_123",
                },
                {
                    "id": "user_api_2",
                    "email": "operador.web@example.com",
                    "name": "Operador Web",
                    "role": "OPERADOR",
                    "companyId": "company_api_123",
                },
            ]

        desktop_users.API_LIST_USERS_CLIENT = fake_remote_users

        try:
            users = desktop_users.list_public_users(current_user=current_user)
        finally:
            desktop_users.API_LIST_USERS_CLIENT = None

        usernames = [user["username"] for user in users]
        self.assertEqual(
            [
                "admin.web@example.com",
                "operador.web@example.com",
                "admin.local@example.com",
            ],
            usernames,
        )
        self.assertEqual("synced", users[0]["api_sync_status"])
        self.assertEqual("admin", users[0]["role"])

    def test_footer_prefers_api_sync_status_text(self):
        from interface.gui import BackupGUI

        gui = BackupGUI.__new__(BackupGUI)
        gui.api_sync_status_text = "Sincronizando cadastro com API..."

        self.assertEqual(
            "Sincronizando cadastro com API...",
            gui.build_footer_text(),
        )


if __name__ == "__main__":
    unittest.main()
