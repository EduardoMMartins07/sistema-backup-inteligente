import json
import os
from datetime import datetime

from utils import user_data_paths


SESSION_CONTEXT_PATH = os.path.join("config", "desktop_session_context.json")
_CURRENT_USER = None


def _public_session_context(user):
    user = user or {}
    return {
        "username": user.get("username"),
        "user_id": user.get("api_user_id") or user.get("user_id") or user.get("username"),
        "user_role": user.get("role"),
        "company_id": user.get("company_id") or user.get("api_company_id") or "default",
        "auth_source": user.get("auth_source") or "local",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def set_current_user(user):
    global _CURRENT_USER

    _CURRENT_USER = dict(user or {}) if user else None

    if not _CURRENT_USER:
        return None

    company_id, user_id = user_data_paths.get_scope_from_user(_CURRENT_USER)
    user_data_paths.ensure_user_environment(company_id, user_id)
    save_session_context(_CURRENT_USER)
    return _CURRENT_USER


def get_current_user():
    if _CURRENT_USER:
        return dict(_CURRENT_USER)

    context = load_session_context()

    if not context:
        return None

    return {
        "username": context.get("username"),
        "role": context.get("user_role"),
        "company_id": context.get("company_id") or "default",
        "api_user_id": context.get("user_id"),
        "auth_source": context.get("auth_source") or "local",
    }


def clear_current_user():
    global _CURRENT_USER
    _CURRENT_USER = None

    try:
        os.remove(SESSION_CONTEXT_PATH)
    except OSError:
        pass


def save_session_context(user):
    os.makedirs(os.path.dirname(SESSION_CONTEXT_PATH), exist_ok=True)

    with open(SESSION_CONTEXT_PATH, "w", encoding="utf-8") as file:
        json.dump(_public_session_context(user), file, indent=4, ensure_ascii=False)


def load_session_context():
    if not os.path.exists(SESSION_CONTEXT_PATH):
        return None

    try:
        with open(SESSION_CONTEXT_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    return data if isinstance(data, dict) else None
