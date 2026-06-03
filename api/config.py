import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_DEV_JWT_SECRET = "dev-smartbackup-secret-change-me"


def load_env_file(path=ENV_PATH):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class ApiSettings:
    environment: str
    port: int
    api_base_url: str
    database_url: str
    db_path: str
    storage_root: str
    storage_backend: str
    jwt_secret: str
    jwt_expire_minutes: int
    base_s3_prefix: str
    cors_origins: tuple[str, ...]
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    aws_s3_bucket: str
    aws_endpoint_url: str
    max_upload_size_mb: int
    presigned_url_expires_seconds: int
    seed_admin_password: str
    seed_operator_password: str
    seed_viewer_password: str
    db_pool_min: int
    db_pool_max: int
    db_connect_timeout: int
    auto_migrate: bool
    log_web_timing: bool
    redis_url: str


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _duration_minutes(value, default):
    text = str(value or "").strip().lower()

    if not text:
        return default

    try:
        if text.endswith("d"):
            return int(text[:-1]) * 24 * 60
        if text.endswith("h"):
            return int(text[:-1]) * 60
        if text.endswith("m"):
            return int(text[:-1])
        return int(text)
    except (TypeError, ValueError):
        return default


def _first_env(*names, default=""):
    for name in names:
        value = os.environ.get(name)

        if value not in (None, ""):
            return value

    return default


def _split_origins(value):
    origins = [
        origin.strip()
        for origin in str(value or "").split(",")
        if origin.strip()
    ]
    return tuple(origins)


def _environment():
    return _first_env(
        "SMARTBACKUP_ENV",
        "APP_ENV",
        "NODE_ENV",
        default="development",
    ).strip().lower() or "development"


def _database_url(default_db_path):
    return _first_env(
        "DATABASE_URL",
        default=f"sqlite:///{default_db_path}",
    )


def _db_path_from_url(database_url, fallback):
    parsed = urlparse(database_url)

    if parsed.scheme != "sqlite":
        return fallback

    if parsed.netloc:
        return f"//{parsed.netloc}{parsed.path}"

    path = parsed.path or fallback

    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]

    return path


_SETTINGS_CACHE = None


def get_settings():
    global _SETTINGS_CACHE

    if _SETTINGS_CACHE is not None:
        return _SETTINGS_CACHE

    load_env_file()
    environment = _environment()
    db_path = os.environ.get(
        "SMARTBACKUP_API_DB_PATH",
        str(PROJECT_ROOT / "config" / "api.sqlite3"),
    )
    database_url = _database_url(db_path)
    _SETTINGS_CACHE = ApiSettings(
        environment=environment,
        port=_int_env("PORT", 8000),
        api_base_url=_first_env(
            "API_BASE_URL",
            "API_URL",
            default="http://127.0.0.1:8000",
        ),
        database_url=database_url,
        db_path=_db_path_from_url(database_url, db_path),
        storage_root=os.environ.get(
            "SMARTBACKUP_API_STORAGE_ROOT",
            str(PROJECT_ROOT / "api_storage"),
        ),
        storage_backend=os.environ.get(
            "SMARTBACKUP_API_STORAGE_BACKEND",
            "local",
        ).strip().lower() or "local",
        jwt_secret=_first_env(
            "SMARTBACKUP_JWT_SECRET",
            "JWT_SECRET",
            default=DEFAULT_DEV_JWT_SECRET,
        ),
        jwt_expire_minutes=_int_env(
            "SMARTBACKUP_JWT_EXPIRE_MINUTES",
            _int_env(
                "JWT_EXPIRES_MINUTES",
                _duration_minutes(os.environ.get("JWT_EXPIRES_IN"), 1440),
            ),
        ),
        base_s3_prefix=os.environ.get("SMARTBACKUP_API_BASE_S3_PREFIX", "backups"),
        cors_origins=_split_origins(
            _first_env(
                "CORS_ORIGIN",
                "CORS_ORIGINS",
                default="http://127.0.0.1:8000,http://localhost:8000",
            )
        ),
        aws_access_key_id=_first_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_first_env("AWS_SECRET_ACCESS_KEY"),
        aws_region=_first_env("AWS_REGION", default="sa-east-1"),
        aws_s3_bucket=_first_env("AWS_S3_BUCKET", "AWS_BUCKET_NAME"),
        aws_endpoint_url=_first_env("AWS_ENDPOINT_URL"),
        max_upload_size_mb=_int_env("MAX_UPLOAD_SIZE_MB", 500),
        presigned_url_expires_seconds=_int_env(
            "PRESIGNED_URL_EXPIRES_SECONDS",
            900,
        ),
        seed_admin_password=_first_env("SEED_ADMIN_PASSWORD"),
        seed_operator_password=_first_env("SEED_OPERATOR_PASSWORD"),
        seed_viewer_password=_first_env("SEED_VIEWER_PASSWORD"),
        db_pool_min=_int_env("SMARTBACKUP_DB_POOL_MIN", 0),
        db_pool_max=_int_env("SMARTBACKUP_DB_POOL_MAX", 20),
        db_connect_timeout=_int_env("SMARTBACKUP_DB_CONNECT_TIMEOUT", 10),
        auto_migrate=is_truthy(os.environ.get("SMARTBACKUP_AUTO_MIGRATE", "true")),
        log_web_timing=is_truthy(os.environ.get("SMARTBACKUP_LOG_WEB_TIMING")),
        redis_url=_first_env("REDIS_URL"),
    )

    return _SETTINGS_CACHE


def is_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim", "on"}


def required_environment_variables(settings=None):
    settings = settings or get_settings()
    return {
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "JWT_SECRET": (
            os.environ.get("JWT_SECRET")
            or os.environ.get("SMARTBACKUP_JWT_SECRET")
        ),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWS_REGION": os.environ.get("AWS_REGION"),
        "AWS_S3_BUCKET": os.environ.get("AWS_S3_BUCKET") or os.environ.get("AWS_BUCKET_NAME"),
        "PORT": os.environ.get("PORT"),
    }


def validate_environment(strict=None, settings=None):
    settings = settings or get_settings()

    if strict is None:
        strict = (
            settings.environment == "production"
            or is_truthy(os.environ.get("SMARTBACKUP_REQUIRE_ENV"))
        )

    required = required_environment_variables(settings)
    missing = [name for name, value in required.items() if value in (None, "")]

    if missing and strict:
        raise RuntimeError(
            "Variaveis obrigatorias ausentes: " + ", ".join(sorted(missing))
        )

    return missing


def s3_configured(settings=None):
    settings = settings or get_settings()
    return bool(
        settings.aws_access_key_id
        and settings.aws_secret_access_key
        and settings.aws_region
        and settings.aws_s3_bucket
    )
