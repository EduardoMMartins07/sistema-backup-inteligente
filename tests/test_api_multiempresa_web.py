import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.database import connect, init_db
    from api.services import create_company, create_user
except ModuleNotFoundError as error:
    raise unittest.SkipTest(f"Dependencias da API nao instaladas: {error}")


class ApiMultiempresaWebTests(unittest.TestCase):

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
            "CORS_ORIGIN": os.environ.get("CORS_ORIGIN"),
            "PORT": os.environ.get("PORT"),
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
        os.environ["CORS_ORIGIN"] = "http://frontend.test"
        os.environ["PORT"] = "8000"
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

    def test_health_ready_version_and_cors_headers(self):
        health = self.client.get("/health")
        self.assertEqual(200, health.status_code, health.text)
        self.assertEqual("ok", health.json()["status"])

        version = self.client.get("/version")
        self.assertEqual(200, version.status_code, version.text)
        self.assertEqual("backup-api", version.json()["name"])

        ready = self.client.get("/ready")
        self.assertEqual(200, ready.status_code, ready.text)
        self.assertEqual("ready", ready.json()["status"])

        cors = self.client.options(
            "/auth/login",
            headers={
                "Origin": "http://frontend.test",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(200, cors.status_code, cors.text)
        self.assertEqual(
            "http://frontend.test",
            cors.headers.get("access-control-allow-origin"),
        )

    def setup_first_admin(self):
        response = self.client.post(
            "/setup/first-admin",
            json={
                "companyName": "Empresa Alpha",
                "name": "Admin Alpha",
                "email": "admin.alpha@example.com",
                "password": "senha-admin",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        data = response.json()
        return data, {"Authorization": f"Bearer {data['token']}"}

    def login(self, email, password):
        response = self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(200, response.status_code, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def create_company_user_direct(self, company_name, name, email, password, role):
        db = connect(os.environ["SMARTBACKUP_API_DB_PATH"])

        try:
            company = create_company(db, company_name)
            user = create_user(db, company["id"], name, email, password, role)
            db.commit()
            return company, user
        finally:
            db.close()

    def create_operator_with_backup(self, admin_headers, email="operador@example.com"):
        created = self.client.post(
            "/admin/users",
            headers=admin_headers,
            json={
                "name": "Operador",
                "email": email,
                "password": "senha-operador",
                "role": "OPERADOR",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        operator_headers = self.login(email, "senha-operador")

        device_response = self.client.post(
            "/devices/register",
            headers=operator_headers,
            json={
                "name": "Notebook",
                "hostname": "NOTE-01",
                "identifier": f"id-{email}",
            },
        )
        self.assertEqual(200, device_response.status_code, device_response.text)
        device_id = device_response.json()["deviceId"]

        folder_response = self.client.post(
            "/monitored-folders",
            headers=operator_headers,
            json={
                "deviceId": device_id,
                "path": "C:/Projetos",
                "alias": "Projetos",
            },
        )
        self.assertEqual(200, folder_response.status_code, folder_response.text)
        folder_id = folder_response.json()["folder"]["id"]

        backup_response = self.client.post(
            "/backups",
            headers=operator_headers,
            json={
                "deviceId": device_id,
                "folderId": folder_id,
                "name": "backup.zip",
                "type": "INCREMENTAL",
                "priority": "HIGH",
                "sizeBytes": 3,
                "fileCount": 1,
                "checksum": "abc",
                "metadata": {"os": "Windows"},
                "companyId": "company_intrusa",
            },
        )
        self.assertEqual(200, backup_response.status_code, backup_response.text)
        return operator_headers, device_id, folder_id, backup_response.json()["backup"]

    def test_api_flow_ignores_payload_company_uploads_finishes_and_audits(self):
        setup_data, admin_headers = self.setup_first_admin()
        operator_headers, _, _, backup = self.create_operator_with_backup(admin_headers)

        self.assertEqual(setup_data["user"]["companyId"], backup["companyId"])
        self.assertNotEqual("company_intrusa", backup["companyId"])
        self.assertIn("/backup.zip", backup["s3Key"])

        upload = self.client.post(
            f"/backups/{backup['id']}/upload",
            headers=operator_headers,
            files={"file": ("backup.zip", b"abc", "application/zip")},
        )
        self.assertEqual(200, upload.status_code, upload.text)
        self.assertEqual(3, upload.json()["uploadedBytes"])
        self.assertTrue((self.root / "api_storage").exists())

        finished = self.client.patch(
            f"/backups/{backup['id']}/finish",
            headers=operator_headers,
            json={"status": "SUCCESS"},
        )
        self.assertEqual(200, finished.status_code, finished.text)
        self.assertEqual("SUCCESS", finished.json()["backup"]["status"])

        snapshot = self.client.post(
            "/snapshots",
            headers=operator_headers,
            json={
                "backupId": backup["id"],
                "name": "snapshot-final",
                "sizeBytes": 3,
                "fileCount": 1,
                "checksum": "abc",
            },
        )
        self.assertEqual(200, snapshot.status_code, snapshot.text)
        self.assertEqual(backup["id"], snapshot.json()["snapshot"]["backupId"])

        dashboard = self.client.get("/admin/dashboard", headers=admin_headers)
        self.assertEqual(200, dashboard.status_code, dashboard.text)
        self.assertEqual(1, dashboard.json()["summary"]["backups"])
        self.assertEqual(1, dashboard.json()["summary"]["successfulBackups"])

        audit = self.client.get("/admin/audit-logs", headers=admin_headers)
        self.assertEqual(200, audit.status_code, audit.text)
        events = {item["event"] for item in audit.json()["auditLogs"]}
        self.assertIn("BACKUP_FINISHED", events)
        self.assertIn("SNAPSHOT_CREATED", events)

    def test_presigned_url_endpoint_validates_backup_and_returns_s3_data(self):
        _, admin_headers = self.setup_first_admin()
        operator_headers, _, _, backup = self.create_operator_with_backup(admin_headers)

        class FakeStorage:
            def create_presigned_upload_url(self, key, content_type="application/zip"):
                return {
                    "url": "https://s3.example/upload",
                    "method": "PUT",
                    "bucket": "bucket-test",
                    "key": key,
                    "expiresIn": 900,
                    "headers": {"Content-Type": content_type},
                }

        with patch("api.app.S3StorageService", return_value=FakeStorage()):
            response = self.client.post(
                "/backups/presigned-url",
                headers=operator_headers,
                json={
                    "backupId": backup["id"],
                    "fileName": "backup.zip",
                    "contentType": "application/zip",
                    "sizeBytes": 3,
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(backup["id"], response.json()["backupId"])
        self.assertEqual("https://s3.example/upload", response.json()["upload"]["url"])

    def test_multi_company_isolation_and_operator_scope(self):
        _, alpha_admin_headers = self.setup_first_admin()
        alpha_operator_headers, _, _, alpha_backup = self.create_operator_with_backup(
            alpha_admin_headers,
            email="operador.alpha@example.com",
        )
        _, beta_operator = self.create_company_user_direct(
            "Empresa Beta",
            "Operador Beta",
            "operador.beta@example.com",
            "senha-beta",
            "OPERADOR",
        )
        beta_headers = self.login(beta_operator["email"], "senha-beta")

        device_response = self.client.post(
            "/devices/register",
            headers=beta_headers,
            json={"name": "Desktop Beta", "hostname": "BETA-PC", "identifier": "beta-pc"},
        )
        self.assertEqual(200, device_response.status_code, device_response.text)
        folder_response = self.client.post(
            "/monitored-folders",
            headers=beta_headers,
            json={
                "deviceId": device_response.json()["deviceId"],
                "path": "D:/Financeiro",
                "alias": "Financeiro",
            },
        )
        self.assertEqual(200, folder_response.status_code, folder_response.text)
        beta_backup_response = self.client.post(
            "/backups",
            headers=beta_headers,
            json={
                "deviceId": device_response.json()["deviceId"],
                "folderId": folder_response.json()["folder"]["id"],
                "name": "beta.zip",
            },
        )
        self.assertEqual(200, beta_backup_response.status_code, beta_backup_response.text)
        beta_backup = beta_backup_response.json()["backup"]

        alpha_list = self.client.get("/backups", headers=alpha_admin_headers)
        self.assertEqual(200, alpha_list.status_code, alpha_list.text)
        self.assertEqual([alpha_backup["id"]], [item["id"] for item in alpha_list.json()["backups"]])

        beta_detail_from_alpha_admin = self.client.get(
            f"/backups/{beta_backup['id']}",
            headers=alpha_admin_headers,
        )
        self.assertEqual(404, beta_detail_from_alpha_admin.status_code)

        beta_detail_from_alpha_operator = self.client.get(
            f"/backups/{beta_backup['id']}",
            headers=alpha_operator_headers,
        )
        self.assertEqual(404, beta_detail_from_alpha_operator.status_code)

    def test_viewer_cannot_mutate_and_web_blocks_non_admin(self):
        _, admin_headers = self.setup_first_admin()
        viewer = self.client.post(
            "/admin/users",
            headers=admin_headers,
            json={
                "name": "Viewer",
                "email": "viewer@example.com",
                "password": "senha-viewer",
                "role": "VIEWER",
            },
        )
        self.assertEqual(200, viewer.status_code, viewer.text)
        viewer_headers = self.login("viewer@example.com", "senha-viewer")

        response = self.client.post(
            "/devices/register",
            headers=viewer_headers,
            json={"name": "Viewer PC", "hostname": "VIEW", "identifier": "view"},
        )
        self.assertEqual(403, response.status_code)

        web_response = self.client.post(
            "/web/login",
            data={"email": "viewer@example.com", "password": "senha-viewer"},
            follow_redirects=False,
        )
        self.assertEqual(400, web_response.status_code)
        self.assertNotIn("smartbackup_token", web_response.headers.get("set-cookie", ""))

    def test_device_folder_mismatch_is_rejected(self):
        _, admin_headers = self.setup_first_admin()
        operator_headers, device_id, _, _ = self.create_operator_with_backup(admin_headers)

        second_device = self.client.post(
            "/devices/register",
            headers=operator_headers,
            json={"name": "Desktop", "hostname": "DESK", "identifier": "desk-01"},
        )
        self.assertEqual(200, second_device.status_code, second_device.text)
        second_folder = self.client.post(
            "/monitored-folders",
            headers=operator_headers,
            json={
                "deviceId": second_device.json()["deviceId"],
                "path": "D:/Dados",
                "alias": "Dados",
            },
        )
        self.assertEqual(200, second_folder.status_code, second_folder.text)

        mismatch = self.client.post(
            "/backups",
            headers=operator_headers,
            json={
                "deviceId": device_id,
                "folderId": second_folder.json()["folder"]["id"],
                "name": "mismatch.zip",
            },
        )
        self.assertEqual(404, mismatch.status_code)

    def test_web_setup_login_cookie_and_dashboard(self):
        login_page = self.client.get("/web/login")
        self.assertEqual(200, login_page.status_code)
        self.assertIn("Criar admin", login_page.text)

        response = self.client.post(
            "/web/login",
            data={
                "companyName": "Empresa Alpha",
                "name": "Admin Alpha",
                "email": "admin.web@example.com",
                "password": "senha-admin",
            },
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code, response.text)
        self.assertIn("smartbackup_token", response.headers["set-cookie"])

        dashboard = self.client.get("/web/dashboard")
        self.assertEqual(200, dashboard.status_code)
        self.assertIn("Backups recentes", dashboard.text)
        self.assertIn("Usuarios", dashboard.text)

        users = self.client.get("/web/users")
        self.assertEqual(200, users.status_code)
        self.assertIn("admin.web@example.com", users.text)


if __name__ == "__main__":
    unittest.main()
