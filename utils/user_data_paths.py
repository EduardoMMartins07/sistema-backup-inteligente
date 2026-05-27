import json
import os
import re
import shutil
from datetime import datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DATA_DIR = os.path.join(PROJECT_ROOT, "app_data")
COMPANIES_DIR = os.path.join(APP_DATA_DIR, "companies")
MIGRATION_BACKUP_DIR = os.path.join(APP_DATA_DIR, "migration_backup")

LEGACY_CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
LEGACY_CONFIG_PATH = os.path.join(LEGACY_CONFIG_DIR, "config.json")
LEGACY_HISTORY_PATH = os.path.join(LEGACY_CONFIG_DIR, "backup_history.json")
LEGACY_SCHEDULE_PATH = os.path.join(LEGACY_CONFIG_DIR, "backup_schedule.json")
LEGACY_PRIORITY_STATE_PATH = os.path.join(LEGACY_CONFIG_DIR, "priority_backup_state.json")
LEGACY_MONITORED_FOLDERS_PATH = os.path.join(LEGACY_CONFIG_DIR, "monitored_folders.json")
LEGACY_BACKUP_STATE_PATH = os.path.join(LEGACY_CONFIG_DIR, "backup_state.json")

DEFAULT_FILES = {
    "config.json": {},
    "backup_history.json": [],
    "monitored_folders.json": [],
    "backup_state.json": {},
    "backup_schedule.json": {},
}

LEGACY_TO_USER_FILES = {
    LEGACY_CONFIG_PATH: "config.json",
    LEGACY_HISTORY_PATH: "backup_history.json",
    LEGACY_MONITORED_FOLDERS_PATH: "monitored_folders.json",
    LEGACY_BACKUP_STATE_PATH: "backup_state.json",
    LEGACY_PRIORITY_STATE_PATH: "backup_state.json",
    LEGACY_SCHEDULE_PATH: "backup_schedule.json",
}


def sanitize_scope_id(value, fallback="default"):
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    return text[:120] or fallback


def get_scope_from_user(user):
    user = user or {}
    company_id = (
        user.get("company_id")
        or user.get("api_company_id")
        or user.get("companyId")
        or "default"
    )
    user_id = (
        user.get("api_user_id")
        or user.get("user_id")
        or user.get("userId")
        or user.get("username")
        or "sistema"
    )
    return sanitize_scope_id(company_id), sanitize_scope_id(user_id)


def get_user_data_dir(company_id, user_id):
    return os.path.join(
        COMPANIES_DIR,
        f"company_{sanitize_scope_id(company_id)}",
        "users",
        f"user_{sanitize_scope_id(user_id)}",
    )


def get_user_file_path(company_id, user_id, filename):
    return os.path.join(get_user_data_dir(company_id, user_id), filename)


def get_user_config_path(company_id, user_id):
    return get_user_file_path(company_id, user_id, "config.json")


def get_user_backup_history_path(company_id, user_id):
    return get_user_file_path(company_id, user_id, "backup_history.json")


def get_user_monitored_folders_path(company_id, user_id):
    return get_user_file_path(company_id, user_id, "monitored_folders.json")


def get_user_backup_state_path(company_id, user_id):
    return get_user_file_path(company_id, user_id, "backup_state.json")


def get_user_backup_schedule_path(company_id, user_id):
    return get_user_file_path(company_id, user_id, "backup_schedule.json")


def _write_default_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if os.path.exists(path):
        return

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def _copy_legacy_file(source_path, target_path, backup_dir):
    if not os.path.exists(source_path) or os.path.exists(target_path):
        return False

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    shutil.copy2(source_path, target_path)

    os.makedirs(backup_dir, exist_ok=True)
    backup_name = os.path.basename(source_path)
    shutil.copy2(source_path, os.path.join(backup_dir, backup_name))
    return True


def migrate_legacy_files(company_id, user_id):
    user_dir = get_user_data_dir(company_id, user_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(
        MIGRATION_BACKUP_DIR,
        f"company_{sanitize_scope_id(company_id)}",
        f"user_{sanitize_scope_id(user_id)}",
        timestamp,
    )
    migrated = []

    for source_path, filename in LEGACY_TO_USER_FILES.items():
        target_path = os.path.join(user_dir, filename)

        if _copy_legacy_file(source_path, target_path, backup_dir):
            migrated.append(target_path)

    return migrated


def ensure_user_environment(company_id, user_id, migrate_legacy=True):
    if migrate_legacy:
        migrate_legacy_files(company_id, user_id)

    user_dir = get_user_data_dir(company_id, user_id)
    os.makedirs(os.path.join(user_dir, "logs"), exist_ok=True)

    for filename, default_data in DEFAULT_FILES.items():
        _write_default_json(os.path.join(user_dir, filename), default_data)

    return user_dir


def get_current_scope():
    try:
        from auth.local_context import get_current_user

        user = get_current_user()
    except Exception:
        user = None

    if not user:
        return None

    return get_scope_from_user(user)


def get_current_user_file_path(filename):
    scope = get_current_scope()

    if not scope:
        return None

    company_id, user_id = scope
    ensure_user_environment(company_id, user_id, migrate_legacy=False)
    return get_user_file_path(company_id, user_id, filename)
