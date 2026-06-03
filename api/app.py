from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from time import perf_counter, time
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware
from starlette import status

from api.config import get_settings, s3_configured, validate_environment
from api.database import close_postgres_pool, connect, get_db, init_db, utc_now
from api.dependencies import current_user_from_token, get_current_user, require_roles
from api.logging_config import configure_logging, get_logger
from api.schemas import (
    BackupCreatePayload,
    BackupFinishPayload,
    BackupMetadataPayload,
    CompanyCreatePayload,
    DeviceRegisterPayload,
    DesktopConfigPayload,
    FirstAdminPayload,
    LoginPayload,
    MonitoredFolderPayload,
    PresignedUrlPayload,
    SnapshotPayload,
    UserCreatePayload,
    UserUpdatePayload,
)
from api.security import create_access_token
from api.services import (
    admin_dashboard,
    authenticate_user,
    create_backup,
    create_backup_from_metadata,
    create_company_with_admin,
    create_first_admin,
    create_monitored_folder,
    create_snapshot,
    create_user,
    disable_company_user,
    finish_backup,
    get_backup_for_user_action,
    get_backup_detail,
    get_company_by_id,
    get_desktop_config_cache,
    get_user_by_id,
    list_audit_logs,
    list_backups,
    list_company_folders,
    list_company_users,
    list_device_backups,
    list_devices,
    list_snapshots,
    list_user_backups,
    public_company,
    public_user,
    register_device,
    save_backup_upload,
    save_desktop_config_cache,
    update_company_user,
    users_count,
)
from api.storage import S3StorageService, StorageConfigurationError, enforce_upload_size


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
COOKIE_NAME = "smartbackup_token"
SERVICE_NAME = "backup-api"
SERVICE_VERSION = "1.0.0"
logger = get_logger(__name__)
LOGIN_ATTEMPTS = {}
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 8
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def format_bytes(value):
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0

    units = ["B", "KB", "MB", "GB", "TB"]

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


def format_datetime_br(value):
    if not value:
        return "-"

    if isinstance(value, datetime):
        current = value
    else:
        text = str(value).strip()

        if not text:
            return "-"

        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"

        try:
            current = datetime.fromisoformat(text)
        except ValueError:
            return value

    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    return current.astimezone(BRASILIA_TZ).strftime("%d/%m/%Y %H:%M")


templates.env.filters["bytes"] = format_bytes
templates.env.filters["datetime_br"] = format_datetime_br


def api_backup(backup):
    return {
        "id": backup.get("id"),
        "name": backup.get("name"),
        "type": backup.get("type"),
        "status": backup.get("status"),
        "priority": backup.get("priority"),
        "sizeBytes": backup.get("size_bytes", 0),
        "fileCount": backup.get("file_count", 0),
        "s3Key": backup.get("s3_key"),
        "checksum": backup.get("checksum"),
        "errorMessage": backup.get("error_message", ""),
        "companyId": backup.get("company_id"),
        "userId": backup.get("user_id"),
        "deviceId": backup.get("device_id"),
        "folderId": backup.get("folder_id"),
        "startedAt": backup.get("started_at"),
        "finishedAt": backup.get("finished_at"),
        "createdAt": backup.get("created_at"),
        "updatedAt": backup.get("updated_at"),
        "localPath": backup.get("local_path", ""),
        "metadata": backup.get("metadata", {}),
        "userName": backup.get("user_name"),
        "deviceName": backup.get("device_name"),
        "folderPath": backup.get("folder_path"),
    }


def api_snapshot(snapshot):
    return {
        "id": snapshot.get("id"),
        "name": snapshot.get("name"),
        "backupId": snapshot.get("backup_id"),
        "companyId": snapshot.get("company_id"),
        "userId": snapshot.get("user_id"),
        "deviceId": snapshot.get("device_id"),
        "folderId": snapshot.get("folder_id"),
        "s3Key": snapshot.get("s3_key"),
        "sizeBytes": snapshot.get("size_bytes", 0),
        "fileCount": snapshot.get("file_count", 0),
        "checksum": snapshot.get("checksum", ""),
        "createdAt": snapshot.get("created_at"),
        "backupName": snapshot.get("backup_name"),
        "userName": snapshot.get("user_name"),
        "deviceName": snapshot.get("device_name"),
    }


def api_device(device):
    return {
        "id": device.get("id"),
        "name": device.get("name"),
        "hostname": device.get("hostname"),
        "identifier": device.get("identifier"),
        "userId": device.get("user_id"),
        "companyId": device.get("company_id"),
        "createdAt": device.get("created_at"),
        "updatedAt": device.get("updated_at"),
        "lastSeenAt": device.get("last_seen_at"),
        "userName": device.get("user_name"),
        "userEmail": device.get("user_email"),
    }


def normalize_s3_download_key(value):
    key = str(value or "").strip()

    if key.startswith("s3://"):
        without_scheme = key[len("s3://"):]
        parts = without_scheme.split("/", 1)
        return parts[1] if len(parts) == 2 else ""

    return key


def build_auth_response(user):
    return {
        "token": create_access_token(user),
        "user": public_user(user),
    }


def login_rate_limit_key(request, email):
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}:{str(email or '').strip().lower()}"


def is_login_rate_limited(request, email):
    key = login_rate_limit_key(request, email)
    now = time()
    attempts = [
        timestamp
        for timestamp in LOGIN_ATTEMPTS.get(key, [])
        if now - timestamp < LOGIN_RATE_LIMIT_WINDOW_SECONDS
    ]
    LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS


def record_failed_login(request, email):
    key = login_rate_limit_key(request, email)
    LOGIN_ATTEMPTS.setdefault(key, []).append(time())


def clear_login_attempts(request, email):
    LOGIN_ATTEMPTS.pop(login_rate_limit_key(request, email), None)


def filters_from_query(
    userId=None,
    deviceId=None,
    folderId=None,
    status=None,
    type=None,
    priority=None,
    startDate=None,
    endDate=None,
):
    return {
        "userId": userId,
        "deviceId": deviceId,
        "folderId": folderId,
        "status": status,
        "type": type,
        "priority": priority,
        "startDate": startDate,
        "endDate": endDate,
    }


def web_user(request: Request, db: Connection):
    token = request.cookies.get(COOKIE_NAME)

    if not token:
        return None

    try:
        return current_user_from_token(db, token)
    except Exception:
        return None


def web_redirect_to_login(request: Request):
    return RedirectResponse(f"/web/login?next={request.url.path}", status_code=303)


def web_forbidden(request: Request, current_user):
    return templates.TemplateResponse(
        request,
        "forbidden.html",
        {
            "current_user": current_user,
            "title": "Acesso negado",
        },
        status_code=403,
    )


def require_web_admin(request: Request, db: Connection):
    current_user = web_user(request, db)

    if not current_user:
        return None, web_redirect_to_login(request)

    company = get_company_by_id(db, current_user["company_id"])
    if company:
        current_user["company_name"] = company.get("name") or current_user["company_id"]

    if current_user["role"] != "ADMIN_EMPRESA":
        return current_user, web_forbidden(request, current_user)

    return current_user, None


def require_web_user(request: Request, db: Connection):
    current_user = web_user(request, db)

    if not current_user:
        return None, web_redirect_to_login(request)

    company = get_company_by_id(db, current_user["company_id"])
    if company:
        current_user["company_name"] = company.get("name") or current_user["company_id"]

    return current_user, None


def create_app():
    @asynccontextmanager
    async def lifespan(_app):
        settings = get_settings()
        configure_logging(settings.environment)
        validate_environment(settings=settings)
        logger.info(
            "Starting %s %s in %s",
            SERVICE_NAME,
            SERVICE_VERSION,
            settings.environment,
        )
        if settings.auto_migrate:
            init_db()
        else:
            logger.info("Auto migrations disabled by SMARTBACKUP_AUTO_MIGRATE.")

        try:
            yield
        finally:
            close_postgres_pool()

    settings = get_settings()
    app = FastAPI(
        title="Smart Backup API",
        description="API central multiempresa para o Sistema Inteligente de Backup.",
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )

    if settings.log_web_timing:
        @app.middleware("http")
        async def log_web_timing(request: Request, call_next):
            started_at = perf_counter()
            response = await call_next(request)

            if request.url.path.startswith("/web"):
                duration_ms = (perf_counter() - started_at) * 1000
                logger.info(
                    "web_request path=%s status=%s duration_ms=%.1f",
                    request.url.path,
                    response.status_code,
                    duration_ms,
                )

            return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def root():
        return RedirectResponse("/web/dashboard", status_code=303)

    @app.get("/health")
    def health():
        current_settings = get_settings()
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "environment": current_settings.environment,
            "timestamp": utc_now(),
        }

    @app.get("/version")
    def version():
        current_settings = get_settings()
        return {
            "name": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "commit": "",
            "environment": current_settings.environment,
        }

    @app.get("/ready")
    def ready():
        current_settings = get_settings()
        missing = validate_environment(strict=False, settings=current_settings)
        database_status = "connected"

        try:
            db = connect()
            try:
                db.execute("SELECT 1")
            finally:
                db.close()
        except Exception as error:
            logger.error("Database readiness check failed: %s", error)
            database_status = "disconnected"

        s3_status = "configured" if s3_configured(current_settings) else "not_configured"
        is_ready = (
            database_status == "connected"
            and s3_status == "configured"
            and not missing
        )
        payload = {
            "status": "ready" if is_ready else "not_ready",
            "database": database_status,
            "s3": s3_status,
            "missingEnv": missing,
            "timestamp": utc_now(),
        }
        return JSONResponse(
            payload,
            status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.post("/setup/first-admin")
    def setup_first_admin(payload: FirstAdminPayload, db: Connection = Depends(get_db)):
        company, user = create_first_admin(
            db,
            payload.companyName,
            payload.name,
            payload.email,
            payload.password,
        )
        logger.info("Initial admin created for company=%s", company["id"])
        response = build_auth_response(user)
        response["company"] = public_company(company)
        return response

    @app.post("/api/companies")
    def create_company_api(
        payload: CompanyCreatePayload,
        db: Connection = Depends(get_db),
    ):
        company, user = create_company_with_admin(
            db,
            payload.companyName,
            payload.name,
            payload.email,
            payload.password,
        )
        db.commit()
        logger.info("Company created company=%s admin=%s", company["id"], user["id"])
        response = build_auth_response(user)
        response["company"] = public_company(company)
        return response

    @app.post("/auth/login")
    def auth_login(
        payload: LoginPayload,
        request: Request,
        db: Connection = Depends(get_db),
    ):
        if is_login_rate_limited(request, payload.email):
            return JSONResponse(
                {"detail": "Muitas tentativas de login. Tente novamente em alguns minutos."},
                status_code=429,
            )

        user = authenticate_user(db, payload.email, payload.password)

        if not user:
            logger.warning("Login failed for email=%s", payload.email)
            record_failed_login(request, payload.email)
            return JSONResponse(
                {"detail": "Email ou senha invalidos."},
                status_code=401,
            )

        db.commit()
        clear_login_attempts(request, payload.email)
        logger.info("Login success user=%s company=%s", user["id"], user["company_id"])
        return build_auth_response(user)

    @app.post("/auth/logout")
    def auth_logout():
        return {"status": "logged_out"}

    @app.get("/auth/me")
    def auth_me(current_user=Depends(get_current_user), db: Connection = Depends(get_db)):
        company = get_company_by_id(db, current_user["company_id"])
        return {
            "user": public_user(current_user),
            "company": public_company(company),
        }

    @app.get("/api/config/desktop")
    def get_desktop_config_api(
        deviceId: str | None = None,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        return get_desktop_config_cache(db, current_user, device_id=deviceId)

    @app.put("/api/config/desktop")
    def save_desktop_config_api(
        payload: DesktopConfigPayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        return save_desktop_config_cache(
            db,
            current_user,
            config=payload.config,
            history=payload.history,
            device_id=payload.deviceId,
        )

    @app.get("/admin/dashboard")
    def admin_dashboard_api(
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        return admin_dashboard(db, current_user)

    @app.get("/admin/users")
    def admin_users_api(
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        return {"users": [public_user(user) for user in list_company_users(db, current_user["company_id"])]}

    @app.get("/api/companies/{company_id}/users")
    def company_users_api(
        company_id: str,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        if company_id != current_user["company_id"]:
            return JSONResponse({"detail": "Empresa nao autorizada."}, status_code=403)

        return {"users": [public_user(user) for user in list_company_users(db, company_id)]}

    @app.post("/admin/users")
    def admin_create_user_api(
        payload: UserCreatePayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        user = create_user(
            db,
            current_user["company_id"],
            payload.name,
            payload.email,
            payload.password,
            payload.role,
        )
        db.commit()
        return {"user": public_user(user)}

    @app.patch("/admin/users/{user_id}")
    def admin_update_user_api(
        user_id: str,
        payload: UserUpdatePayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        user = update_company_user(
            db,
            current_user["company_id"],
            user_id,
            name=payload.name,
            role=payload.role,
            status_value=payload.status,
        )
        return {"user": public_user(user)}

    @app.delete("/admin/users/{user_id}")
    def admin_disable_user_api(
        user_id: str,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        user = disable_company_user(db, current_user["company_id"], user_id)
        return {"user": public_user(user)}

    @app.get("/admin/users/{user_id}/backups")
    def admin_user_backups_api(
        user_id: str,
        userId: str | None = None,
        deviceId: str | None = None,
        folderId: str | None = None,
        status: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        filters = filters_from_query(userId, deviceId, folderId, status, type, priority, startDate, endDate)
        backups = list_user_backups(db, current_user, user_id, filters=filters)
        return {"backups": [api_backup(backup) for backup in backups]}

    @app.get("/admin/devices/{device_id}/backups")
    def admin_device_backups_api(
        device_id: str,
        userId: str | None = None,
        deviceId: str | None = None,
        folderId: str | None = None,
        status: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        filters = filters_from_query(userId, deviceId, folderId, status, type, priority, startDate, endDate)
        backups = list_device_backups(db, current_user, device_id, filters=filters)
        return {"backups": [api_backup(backup) for backup in backups]}

    @app.get("/admin/audit-logs")
    def admin_audit_logs_api(
        event: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        logs = list_audit_logs(
            db,
            current_user,
            filters={"event": event, "startDate": startDate, "endDate": endDate},
        )
        return {"auditLogs": logs}

    @app.post("/devices/register")
    def register_device_api(
        payload: DeviceRegisterPayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        device, action = register_device(
            db,
            current_user,
            payload.name,
            payload.hostname,
            payload.identifier,
        )
        return {
            "deviceId": device["id"],
            "status": "registered" if action in {"registered", "updated"} else action,
            "device": api_device(device),
        }

    @app.post("/monitored-folders")
    def monitored_folder_api(
        payload: MonitoredFolderPayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        folder = create_monitored_folder(
            db,
            current_user,
            payload.deviceId,
            payload.path,
            payload.alias,
        )
        return {
            "folder": {
                "id": folder["id"],
                "path": folder["path"],
                "alias": folder["alias"],
                "deviceId": folder["device_id"],
                "userId": folder["user_id"],
                "companyId": folder["company_id"],
            }
        }

    @app.post("/backups")
    def create_backup_api(
        payload: BackupCreatePayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        backup = create_backup(db, current_user, payload)
        logger.info(
            "Backup created backup=%s user=%s company=%s",
            backup["id"],
            current_user["id"],
            current_user["company_id"],
        )
        return {"backup": api_backup(backup)}

    @app.post("/api/backups")
    def create_backup_metadata_api(
        payload: BackupMetadataPayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        backup = create_backup_from_metadata(db, current_user, payload)
        return {"backup": api_backup(backup)}

    @app.get("/backups")
    def list_backups_api(
        userId: str | None = None,
        deviceId: str | None = None,
        folderId: str | None = None,
        status: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        filters = filters_from_query(userId, deviceId, folderId, status, type, priority, startDate, endDate)
        backups = list_backups(db, current_user, filters=filters)
        return {"backups": [api_backup(backup) for backup in backups]}

    @app.get("/api/companies/{company_id}/backups")
    def company_backups_api(
        company_id: str,
        userId: str | None = None,
        deviceId: str | None = None,
        folderId: str | None = None,
        status: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        page: int | None = None,
        limit: int | None = None,
        current_user=Depends(require_roles(["ADMIN_EMPRESA"])),
        db: Connection = Depends(get_db),
    ):
        if company_id != current_user["company_id"]:
            return JSONResponse({"detail": "Empresa nao autorizada."}, status_code=403)

        filters = filters_from_query(userId, deviceId, folderId, status, type, priority, startDate, endDate)
        backups = list_backups(db, current_user, filters=filters, limit=limit or 200)
        return {"backups": [api_backup(backup) for backup in backups], "page": page or 1}

    @app.get("/api/me/backups")
    def my_backups_api(
        deviceId: str | None = None,
        folderId: str | None = None,
        status: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        limit: int | None = None,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        filters = filters_from_query(
            current_user["id"],
            deviceId,
            folderId,
            status,
            type,
            priority,
            startDate,
            endDate,
        )
        backups = list_backups(db, current_user, filters=filters, limit=limit or 200)
        return {"backups": [api_backup(backup) for backup in backups]}

    @app.post("/backups/presigned-url")
    def create_presigned_upload_url_api(
        payload: PresignedUrlPayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        backup = get_backup_for_user_action(db, current_user, payload.backupId, mutate=True)
        enforce_upload_size(payload.sizeBytes or backup.get("size_bytes") or 0)
        content_type = payload.contentType or "application/zip"

        try:
            presigned = S3StorageService().create_presigned_upload_url(
                backup["s3_key"],
                content_type=content_type,
            )
        except StorageConfigurationError as error:
            return JSONResponse(
                {"detail": str(error)},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return {
            "backupId": backup["id"],
            "s3Key": backup["s3_key"],
            "upload": presigned,
        }

    @app.post("/backups/{backup_id}/upload")
    def upload_backup_api(
        backup_id: str,
        file: UploadFile = File(...),
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        backup = save_backup_upload(db, current_user, backup_id, file)
        logger.info("Backup upload completed backup=%s", backup["id"])
        return {
            "backupId": backup["id"],
            "s3Key": backup["s3_key"],
            "uploadedBytes": backup["uploadedBytes"],
            "status": "uploaded",
        }

    @app.patch("/backups/{backup_id}/finish")
    def finish_backup_api(
        backup_id: str,
        payload: BackupFinishPayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        backup = finish_backup(db, current_user, backup_id, payload)
        logger.info("Backup finished backup=%s status=%s", backup["id"], backup["status"])
        return {"backup": api_backup(backup)}

    @app.get("/backups/{backup_id}/snapshots")
    def backup_snapshots_api(
        backup_id: str,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        snapshots = list_snapshots(db, current_user, backup_id=backup_id)
        return {"snapshots": [api_snapshot(snapshot) for snapshot in snapshots]}

    @app.get("/backups/{backup_id}")
    def backup_detail_api(
        backup_id: str,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        backup = get_backup_detail(db, current_user, backup_id)
        serialized = api_backup(backup)
        serialized["snapshots"] = [api_snapshot(snapshot) for snapshot in backup["snapshots"]]
        return {"backup": serialized}

    @app.get("/api/backups/{backup_id}")
    def api_backup_detail_alias(
        backup_id: str,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        backup = get_backup_detail(db, current_user, backup_id)
        serialized = api_backup(backup)
        serialized["snapshots"] = [api_snapshot(snapshot) for snapshot in backup["snapshots"]]
        return {"backup": serialized}

    @app.get("/api/backups/{backup_id}/download")
    def api_backup_download_alias(
        backup_id: str,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        backup = get_backup_for_user_action(db, current_user, backup_id)
        s3_key = normalize_s3_download_key(backup.get("s3_key"))

        if not s3_key:
            return JSONResponse(
                {"detail": "Backup sem objeto remoto registrado."},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            download = S3StorageService().create_presigned_download_url(s3_key)
        except StorageConfigurationError as error:
            return JSONResponse(
                {"detail": str(error)},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return {
            "backupId": backup["id"],
            "s3Key": s3_key,
            "download": download,
        }

    @app.post("/snapshots")
    def create_snapshot_api(
        payload: SnapshotPayload,
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR"])),
        db: Connection = Depends(get_db),
    ):
        snapshot = create_snapshot(db, current_user, payload)
        return {"snapshot": api_snapshot(snapshot)}

    @app.get("/snapshots")
    def list_snapshots_api(
        current_user=Depends(require_roles(["ADMIN_EMPRESA", "OPERADOR", "VIEWER"])),
        db: Connection = Depends(get_db),
    ):
        snapshots = list_snapshots(db, current_user)
        return {"snapshots": [api_snapshot(snapshot) for snapshot in snapshots]}

    @app.get("/web/login", response_class=HTMLResponse)
    def web_login(
        request: Request,
        next: str | None = None,
        signup: str | None = None,
        db: Connection = Depends(get_db),
    ):
        current_user = web_user(request, db)

        if current_user:
            target = "/web/dashboard" if current_user["role"] == "ADMIN_EMPRESA" else "/web/my-backups"
            return RedirectResponse(next or target, status_code=303)

        signup_mode = str(signup or "").lower() in {"1", "true", "yes", "sim"}
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "title": "Login",
                "setup_required": users_count(db) == 0,
                "signup_mode": signup_mode,
                "error": "",
                "next": next or "/web/dashboard",
            },
        )

    @app.post("/web/login")
    def web_login_post(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        name: str = Form(default=""),
        companyName: str = Form(default="Empresa"),
        action: str = Form(default="login"),
        next: str = Form(default="/web/dashboard"),
        db: Connection = Depends(get_db),
    ):
        setup_required = users_count(db) == 0
        signup_mode = action == "signup"

        try:
            if signup_mode:
                _, user = create_company_with_admin(
                    db,
                    companyName,
                    name or email,
                    email,
                    password,
                )
                db.commit()
            elif setup_required:
                _, user = create_first_admin(
                    db,
                    companyName,
                    name or email,
                    email,
                    password,
                )
            else:
                if is_login_rate_limited(request, email):
                    raise ValueError(
                        "Muitas tentativas de login. Tente novamente em alguns minutos."
                    )

                user = authenticate_user(db, email, password)

                if not user:
                    record_failed_login(request, email)
                    raise ValueError("Email ou senha invalidos.")

                db.commit()
                clear_login_attempts(request, email)
        except Exception as error:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "title": "Login",
                    "setup_required": setup_required,
                    "signup_mode": signup_mode,
                    "error": str(getattr(error, "detail", error)),
                    "next": next,
                },
                status_code=400,
            )

        target = next or "/web/dashboard"

        if user["role"] != "ADMIN_EMPRESA" and target == "/web/dashboard":
            target = "/web/my-backups"

        response = RedirectResponse(target, status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            create_access_token(user),
            httponly=True,
            samesite="lax",
        )
        return response

    @app.post("/web/logout")
    def web_logout():
        response = RedirectResponse("/web/login", status_code=303)
        response.delete_cookie(COOKIE_NAME)
        return response

    @app.get("/web/dashboard", response_class=HTMLResponse)
    def web_dashboard(request: Request, db: Connection = Depends(get_db)):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        data = admin_dashboard(db, current_user)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "title": "Dashboard",
                "current_user": current_user,
                "company": data["company"],
                "summary": data["summary"],
                "recent_backups": data["recentBackups"],
            },
        )

    @app.get("/web/users", response_class=HTMLResponse)
    def web_users(request: Request, db: Connection = Depends(get_db)):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        return templates.TemplateResponse(
            request,
            "users.html",
            {
                "title": "Usuários",
                "current_user": current_user,
                "users": list_company_users(db, current_user["company_id"]),
            },
        )

    @app.post("/web/users")
    def web_users_create(
        request: Request,
        name: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        role: str = Form(...),
        db: Connection = Depends(get_db),
    ):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        create_user(db, current_user["company_id"], name, email, password, role)
        db.commit()
        return RedirectResponse("/web/users", status_code=303)

    @app.post("/web/users/{user_id}/update")
    def web_users_update(
        user_id: str,
        request: Request,
        name: str = Form(...),
        role: str = Form(...),
        status_value: str = Form(default="ACTIVE", alias="status"),
        db: Connection = Depends(get_db),
    ):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        update_company_user(
            db,
            current_user["company_id"],
            user_id,
            name=name,
            role=role,
            status_value=status_value,
        )
        return RedirectResponse("/web/users", status_code=303)

    @app.post("/web/users/{user_id}/disable")
    def web_users_disable(
        user_id: str,
        request: Request,
        db: Connection = Depends(get_db),
    ):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        disable_company_user(db, current_user["company_id"], user_id)
        return RedirectResponse("/web/users", status_code=303)

    @app.get("/web/devices", response_class=HTMLResponse)
    def web_devices(request: Request, db: Connection = Depends(get_db)):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        return templates.TemplateResponse(
            request,
            "devices.html",
            {
                "title": "Dispositivos",
                "current_user": current_user,
                "devices": list_devices(db, current_user),
            },
        )

    @app.get("/web/backups", response_class=HTMLResponse)
    def web_backups(
        request: Request,
        userId: str | None = None,
        deviceId: str | None = None,
        folderId: str | None = None,
        status: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        db: Connection = Depends(get_db),
    ):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        filters = filters_from_query(userId, deviceId, folderId, status, type, priority, startDate, endDate)
        return templates.TemplateResponse(
            request,
            "backups.html",
            {
                "title": "Backups",
                "current_user": current_user,
                "backups": list_backups(db, current_user, filters=filters),
                "users": list_company_users(db, current_user["company_id"]),
                "devices": list_devices(db, current_user),
                "folders": list_company_folders(db, current_user),
                "filters": filters,
                "personal_view": False,
            },
        )

    @app.get("/web/my-backups", response_class=HTMLResponse)
    def web_my_backups(
        request: Request,
        status: str | None = None,
        type: str | None = None,
        priority: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        db: Connection = Depends(get_db),
    ):
        current_user, response = require_web_user(request, db)

        if response:
            return response

        filters = filters_from_query(
            current_user["id"],
            None,
            None,
            status,
            type,
            priority,
            startDate,
            endDate,
        )
        return templates.TemplateResponse(
            request,
            "backups.html",
            {
                "title": "Meus Backups",
                "current_user": current_user,
                "backups": list_backups(db, current_user, filters=filters),
                "users": [],
                "devices": [],
                "folders": [],
                "filters": filters,
                "personal_view": True,
            },
        )

    @app.get("/web/backups/{backup_id}", response_class=HTMLResponse)
    def web_backup_detail(
        backup_id: str,
        request: Request,
        db: Connection = Depends(get_db),
    ):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        backup = get_backup_detail(db, current_user, backup_id)
        return templates.TemplateResponse(
            request,
            "backup_detail.html",
            {
                "title": backup["name"],
                "current_user": current_user,
                "backup": backup,
            },
        )

    @app.get("/web/snapshots", response_class=HTMLResponse)
    def web_snapshots(request: Request, db: Connection = Depends(get_db)):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        return templates.TemplateResponse(
            request,
            "snapshots.html",
            {
                "title": "Snapshots",
                "current_user": current_user,
                "snapshots": list_snapshots(db, current_user),
            },
        )

    @app.get("/web/audit-logs", response_class=HTMLResponse)
    def web_audit_logs(
        request: Request,
        event: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        db: Connection = Depends(get_db),
    ):
        current_user, response = require_web_admin(request, db)

        if response:
            return response

        filters = {"event": event, "startDate": startDate, "endDate": endDate}
        return templates.TemplateResponse(
            request,
            "audit_logs.html",
            {
                "title": "Auditoria",
                "current_user": current_user,
                "logs": list_audit_logs(db, current_user, filters=filters),
                "filters": filters,
            },
        )

    return app


app = create_app()
