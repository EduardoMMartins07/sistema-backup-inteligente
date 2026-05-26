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
