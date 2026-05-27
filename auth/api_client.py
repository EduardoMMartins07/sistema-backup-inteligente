import os

import httpx


API_TO_DESKTOP_ROLES = {
    "ADMIN_EMPRESA": "admin",
    "OPERADOR": "operator",
    "VIEWER": "viewer",
}
DESKTOP_TO_API_ROLES = {
    "admin": "ADMIN_EMPRESA",
    "operator": "OPERADOR",
    "viewer": "VIEWER",
}


def get_api_base_url():
    try:
        from api.config import load_env_file

        load_env_file()
    except Exception:
        pass

    base_url = os.environ.get("API_BASE_URL") or os.environ.get("API_URL")
    return str(base_url or "").strip().rstrip("/")


def is_configured():
    return bool(get_api_base_url())


def _post_json(path, payload, token=None, timeout=8):
    headers = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.post(
        f"{get_api_base_url()}{path}",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _get_json(path, token, params=None, timeout=8):
    response = httpx.get(
        f"{get_api_base_url()}{path}",
        params=params or {},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _put_json(path, payload, token, timeout=8):
    response = httpx.put(
        f"{get_api_base_url()}{path}",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _history_status_to_api(status):
    normalized = str(status or "").strip().lower()
    return {
        "completed": "success",
        "success": "success",
        "failed": "failed",
        "cancelled": "canceled",
        "canceled": "canceled",
    }.get(normalized, "running")


def _history_type_to_api(entry):
    if entry.get("history_group_type") == "priority_snapshot":
        return "snapshot"

    if entry.get("storage_mode") == "full":
        return "full"

    return "incremental"


def _snapshot_items_from_history(entry):
    file_snapshot = entry.get("file_snapshot")

    if isinstance(file_snapshot, dict) and file_snapshot:
        return [
            dict(file_data, archive_name=archive_name)
            for archive_name, file_data in file_snapshot.items()
            if isinstance(file_data, dict)
        ]

    changes = entry.get("file_changes")
    return changes if isinstance(changes, list) else []


def backup_metadata_from_history(entry):
    backup_id = entry.get("backup_id") or entry.get("snapshot_id")

    if not backup_id:
        backup_path = entry.get("snapshot_path") or entry.get("backup_path") or ""
        backup_id = os.path.splitext(os.path.basename(backup_path))[0]

    return {
        "backup_id": backup_id,
        "company_id": entry.get("company_id"),
        "user_id": entry.get("api_user_id"),
        "user_name": entry.get("user_name") or entry.get("user"),
        "backup_name": (
            entry.get("backup_name")
            or entry.get("backup_file")
            or entry.get("snapshot_id")
            or "Backup local"
        ),
        "backup_type": _history_type_to_api(entry),
        "priority": entry.get("priority") or "normal",
        "status": _history_status_to_api(entry.get("status")),
        "created_at": entry.get("started_at") or entry.get("created_at"),
        "started_at": entry.get("started_at"),
        "finished_at": entry.get("finished_at"),
        "file_count": entry.get("total_files") or 0,
        "total_size_bytes": entry.get("compacted_size_bytes") or 0,
        "storage_target": entry.get("cloud_provider") or entry.get("storage_mode") or "local",
        "remote_path": entry.get("cloud_snapshot_key") or entry.get("backup_path") or "",
        "local_path": entry.get("snapshot_path") or entry.get("backup_path") or "",
        "items": _snapshot_items_from_history(entry),
        "metadata": {
            "source": "desktop_history",
            "cloudSyncStatus": entry.get("cloud_sync_status"),
            "cloudStoragePrefix": entry.get("cloud_storage_prefix"),
            "trigger": entry.get("trigger"),
            "storageMode": entry.get("storage_mode"),
        },
    }


def desktop_user_from_api(payload):
    user = payload.get("user", payload) if isinstance(payload, dict) else {}
    company_id = user.get("companyId") or user.get("company_id") or payload.get("companyId")
    role = API_TO_DESKTOP_ROLES.get(user.get("role"), user.get("role"))
    desktop_user = {
        "username": user.get("email") or user.get("username"),
        "name": user.get("name") or user.get("email") or user.get("username"),
        "role": role,
        "company_id": company_id,
        "api_user_id": user.get("id") or user.get("userId"),
        "api_company_id": company_id,
        "api_sync_status": "synced",
        "auth_source": "api",
    }

    if payload.get("token"):
        desktop_user["auth_token"] = payload["token"]

    return desktop_user


def login(email, password):
    payload = _post_json(
        "/auth/login",
        {"email": email, "password": password},
    )
    return desktop_user_from_api(payload)


def create_company(company_name, name, email, password):
    payload = _post_json(
        "/api/companies",
        {
            "companyName": company_name,
            "name": name,
            "email": email,
            "password": password,
        },
    )
    return desktop_user_from_api(payload), payload


def create_user(token, user, password):
    payload = _post_json(
        "/admin/users",
        {
            "name": user.get("name") or user.get("username"),
            "email": user.get("username"),
            "password": password,
            "role": DESKTOP_TO_API_ROLES.get(user.get("role"), user.get("role")),
        },
        token=token,
    )
    return payload.get("user", payload)


def list_company_users(token):
    payload = _get_json("/admin/users", token)
    users = payload.get("users", []) if isinstance(payload, dict) else []
    return [
        desktop_user_from_api({"user": user})
        for user in users
        if isinstance(user, dict)
    ]


def list_company_users_for_company(token, company_id):
    payload = _get_json(f"/api/companies/{company_id}/users", token)
    users = payload.get("users", []) if isinstance(payload, dict) else []
    return [
        desktop_user_from_api({"user": user})
        for user in users
        if isinstance(user, dict)
    ]


def list_company_backups(token, company_id, filters=None):
    payload = _get_json(f"/api/companies/{company_id}/backups", token, params=filters or {})
    return payload.get("backups", []) if isinstance(payload, dict) else []


def list_my_backups(token, filters=None):
    payload = _get_json("/api/me/backups", token, params=filters or {})
    return payload.get("backups", []) if isinstance(payload, dict) else []


def register_backup_metadata(token, history_entry):
    payload = (
        backup_metadata_from_history(history_entry)
        if isinstance(history_entry, dict)
        else history_entry
    )
    return _post_json("/api/backups", payload, token=token)


def get_backup_detail(token, backup_id):
    return _get_json(f"/api/backups/{backup_id}", token)


def get_desktop_config(token, device_id=None):
    params = {"deviceId": device_id} if device_id else None
    return _get_json("/api/config/desktop", token, params=params)


def save_desktop_config(token, config, history, device_id=None):
    return _put_json(
        "/api/config/desktop",
        {
            "config": config or {},
            "history": history or [],
            "deviceId": device_id,
        },
        token,
    )
