import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


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
    db_path: str
    storage_root: str
    storage_backend: str
    jwt_secret: str
    jwt_expire_minutes: int
    base_s3_prefix: str


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def get_settings():
    load_env_file()
    return ApiSettings(
        db_path=os.environ.get(
            "SMARTBACKUP_API_DB_PATH",
            str(PROJECT_ROOT / "config" / "api.sqlite3"),
        ),
        storage_root=os.environ.get(
            "SMARTBACKUP_API_STORAGE_ROOT",
            str(PROJECT_ROOT / "api_storage"),
        ),
        storage_backend=os.environ.get(
            "SMARTBACKUP_API_STORAGE_BACKEND",
            "local",
        ).strip().lower() or "local",
        jwt_secret=os.environ.get(
            "SMARTBACKUP_JWT_SECRET",
            "dev-smartbackup-secret-change-me",
        ),
        jwt_expire_minutes=_int_env("SMARTBACKUP_JWT_EXPIRE_MINUTES", 1440),
        base_s3_prefix=os.environ.get("SMARTBACKUP_API_BASE_S3_PREFIX", "backups"),
    )

