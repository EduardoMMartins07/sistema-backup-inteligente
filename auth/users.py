import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime

from auth.permissions import ROLES
from security import crypto_service

USERS_PATH = os.path.join("config", "users.json")
PBKDF2_ITERATIONS = 260000
DEFAULT_COMPANY_ID = "default"
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
API_SYNC_PENDING_STATUSES = {"pending", "failed"}
API_LOGIN_CLIENT = None
API_LIST_USERS_CLIENT = None


def load_users():
    if not os.path.exists(USERS_PATH):
        return []

    with open(USERS_PATH, "r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return []

    if isinstance(data, list):
        return data

    return []


def save_users(users):
    os.makedirs(os.path.dirname(USERS_PATH), exist_ok=True)
    persisted_users = []

    for user in users:
        persisted_users.append(
            {
                key: value
                for key, value in user.items()
                if not str(key).startswith("_")
            }
        )

    with open(USERS_PATH, "w", encoding="utf-8") as file:
        json.dump(persisted_users, file, indent=4, ensure_ascii=False)


def users_exist():
    if load_users():
        return True

    return api_users_exist()


def normalize_username(username):
    return str(username or "").strip().lower()


def normalize_name(name):
    return " ".join(str(name or "").strip().lower().split())


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS
    )
    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(password_hash).decode("ascii"),
        "iterations": PBKDF2_ITERATIONS,
    }


def verify_password(password, password_data):
    try:
        salt = base64.b64decode(password_data["salt"])
        expected_hash = base64.b64decode(password_data["hash"])
        iterations = int(password_data.get("iterations", PBKDF2_ITERATIONS))
    except (KeyError, TypeError, ValueError):
        return False

    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations
    )
    return hmac.compare_digest(actual_hash, expected_hash)


def find_user(username):
    normalized_username = normalize_username(username)

    for user in load_users():
        if user.get("username") == normalized_username:
            return user

    return None


def public_user(user):
    if not user:
        return None

    public_data = {
        "username": user.get("username"),
        "name": user.get("name", user.get("username")),
        "role": user.get("role"),
        "company_id": user.get("company_id", DEFAULT_COMPANY_ID),
        "created_at": user.get("created_at"),
    }

    for key in (
        "api_sync_status",
        "api_user_id",
        "api_company_id",
        "api_sync_error",
        "api_synced_at",
        "auth_source",
        "auth_token",
        "api_sync_action",
        "company_name",
    ):
        if user.get(key):
            public_data[key] = user.get(key)

    if user.get("_session_master_key"):
        public_data["session_master_key"] = user["_session_master_key"]

    if user.get("_recovery_key"):
        public_data["recovery_key"] = user["_recovery_key"]

    return public_data


def user_has_crypto_metadata(user):
    return bool(
        user.get("kdf_salt")
        and user.get("encrypted_master_key")
        and user.get("master_key_nonce")
    )


def attach_new_crypto_metadata(user, password):
    metadata, master_key, recovery_key = crypto_service.create_user_crypto_metadata(password)
    user.update(metadata)
    user["_session_master_key"] = crypto_service.b64encode(master_key)

    if recovery_key:
        user["_recovery_key"] = recovery_key

    return master_key


def authenticate(username, password):
    normalized_username = normalize_username(username)

    api_user = authenticate_api_http_user(normalized_username, password)

    if api_user:
        cache_api_user(api_user, password)
        return api_user

    users = load_users()
    user = None

    for current_user in users:
        if current_user.get("username") == normalized_username:
            user = current_user
            break

    if not user:
        return authenticate_api_user(normalized_username, password)

    # For accounts already synced with the API, prefer the authoritative API
    # record before falling back to the desktop cache. This keeps role changes
    # made on the web from being masked by stale local data.
    if user.get("api_user_id") or user.get("auth_source") == "api":
        api_user = authenticate_api_user(normalized_username, password)

        if api_user:
            cache_api_user(api_user, password)
            return api_user

    if not verify_password(password, user.get("password", {})):
        return None

    if not user.get("company_id"):
        user["company_id"] = DEFAULT_COMPANY_ID

    if crypto_service.is_crypto_available():
        try:
            if not user_has_crypto_metadata(user):
                attach_new_crypto_metadata(user, password)
                user["updated_at"] = datetime.now().isoformat(timespec="seconds")
                save_users(users)
            else:
                master_key = crypto_service.decrypt_user_master_key(password, user)
                user["_session_master_key"] = crypto_service.b64encode(master_key)
        except (KeyError, TypeError, ValueError, crypto_service.CryptoError):
            return None

    return public_user(user)


def api_users_exist():
    try:
        from api.database import connect

        connection = connect()

        try:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM users WHERE status = 'ACTIVE'"
            ).fetchone()
            return bool(row and row["total"])
        finally:
            connection.close()
    except Exception:
        return False


def authenticate_api_user(username, password):
    try:
        from api.database import connect, row_to_dict
        from api.security import verify_password as verify_api_password

        connection = connect()

        try:
            row = connection.execute(
                """
                SELECT *
                FROM users
                WHERE email = ? AND status = 'ACTIVE'
                """,
                (normalize_username(username),),
            ).fetchone()
            user = row_to_dict(row)

            if not user:
                return None

            if not verify_api_password(password, user.get("password_hash", "")):
                return None

            return public_api_user(user)
        finally:
            connection.close()
    except Exception:
        return None


def public_api_user(user):
    role = API_TO_DESKTOP_ROLES.get(user.get("role"))

    if not role:
        return None
    auth_token = ""

    try:
        from api.security import create_access_token

        auth_token = create_access_token(user)
    except Exception:
        auth_token = ""

    public_data = {
        "username": user.get("email"),
        "name": user.get("name") or user.get("email"),
        "role": role,
        "company_id": user.get("company_id", DEFAULT_COMPANY_ID),
        "created_at": user.get("created_at"),
        "api_user_id": user.get("id"),
        "api_company_id": user.get("company_id", DEFAULT_COMPANY_ID),
        "api_sync_status": "synced",
        "auth_source": "api",
    }

    if auth_token:
        public_data["auth_token"] = auth_token

    return public_data


def validate_user_payload(username, password, role):
    normalized_username = normalize_username(username)

    if not normalized_username:
        raise ValueError("Informe um nome de usuario.")

    if len(normalized_username) < 3:
        raise ValueError("O usuario deve ter ao menos 3 caracteres.")

    if password is not None and len(password) < 6:
        raise ValueError("A senha deve ter ao menos 6 caracteres.")

    if role not in ROLES:
        raise ValueError("Perfil de permissao invalido.")

    return normalized_username


def create_user(
    username,
    password,
    role,
    name=None,
    company_id=None,
    api_sync_status=None,
    api_user_id=None,
    api_company_id=None,
    api_sync_action=None,
    company_name=None,
):
    normalized_username = validate_user_payload(username, password, role)
    users = load_users()
    display_name = name.strip() if name and name.strip() else normalized_username
    normalized_display_name = normalize_name(display_name)
    effective_company_id = company_id or api_company_id or DEFAULT_COMPANY_ID

    if any(
        user.get("username") == normalized_username
        and user.get("company_id", DEFAULT_COMPANY_ID) == effective_company_id
        for user in users
    ):
        raise ValueError("Ja existe esse usuario cadastrado.")

    if any(
        normalize_name(user.get("name")) == normalized_display_name
        and user.get("company_id", DEFAULT_COMPANY_ID) == effective_company_id
        for user in users
    ):
        raise ValueError("Ja existe um usuario com esse nome de exibicao.")

    now = datetime.now().isoformat(timespec="seconds")
    sync_status = api_sync_status

    if sync_status is None:
        sync_status = "pending" if os.environ.get("API_BASE_URL") else "local"

    user = {
        "username": normalized_username,
        "name": display_name,
        "role": role,
        "company_id": effective_company_id,
        "password": hash_password(password),
        "created_at": now,
        "updated_at": now,
        "api_sync_status": sync_status,
    }

    if api_user_id:
        user["api_user_id"] = api_user_id

    if api_company_id:
        user["api_company_id"] = api_company_id
        user["company_id"] = api_company_id

    if api_sync_action:
        user["api_sync_action"] = api_sync_action

    if company_name:
        user["company_name"] = company_name

    if sync_status in API_SYNC_PENDING_STATUSES or sync_status == "syncing":
        user["api_sync_password"] = password

    if crypto_service.is_crypto_available():
        attach_new_crypto_metadata(user, password)

    users.append(user)
    save_users(users)
    return public_user(user)


def authenticate_api_http_user(username, password):
    try:
        if API_LOGIN_CLIENT is not None:
            return API_LOGIN_CLIENT(username, password)

        from auth import api_client

        if not api_client.is_configured():
            return None

        return api_client.login(username, password)
    except Exception:
        return None


def cache_api_user(api_user, password):
    if not api_user:
        return

    users = load_users()
    normalized_username = normalize_username(api_user.get("username"))

    if not normalized_username:
        return

    now = datetime.now().isoformat(timespec="seconds")

    for user in users:
        if user.get("username") != normalized_username:
            continue

        user["name"] = api_user.get("name") or user.get("name") or normalized_username
        user["role"] = api_user.get("role") or user.get("role")
        user["company_id"] = api_user.get("company_id") or user.get("company_id", DEFAULT_COMPANY_ID)
        user["api_company_id"] = api_user.get("api_company_id") or user.get("company_id")
        user["api_user_id"] = api_user.get("api_user_id") or user.get("api_user_id")
        user["api_sync_status"] = "synced"
        user["auth_source"] = "api"
        user["updated_at"] = now
        user["password"] = hash_password(password)
        user.pop("api_sync_password", None)
        save_users(users)
        return

    user = {
        "username": normalized_username,
        "name": api_user.get("name") or normalized_username,
        "role": api_user.get("role"),
        "company_id": api_user.get("company_id") or DEFAULT_COMPANY_ID,
        "api_company_id": api_user.get("api_company_id") or api_user.get("company_id"),
        "api_user_id": api_user.get("api_user_id"),
        "api_sync_status": "synced",
        "auth_source": "api",
        "password": hash_password(password),
        "created_at": now,
        "updated_at": now,
    }
    users.append(user)
    save_users(users)


def _remote_user_field(payload, *keys):
    current = payload or {}

    if isinstance(current, dict) and isinstance(current.get("user"), dict):
        current = current["user"]

    for key in keys:
        if isinstance(current, dict) and current.get(key):
            return current.get(key)

    return None


def sync_pending_api_users(create_remote_user, status_callback=None):
    users = load_users()
    synced = 0

    for user in users:
        if user.get("api_sync_status") not in API_SYNC_PENDING_STATUSES:
            continue

        password = user.get("api_sync_password")

        if not password:
            user["api_sync_status"] = "failed"
            user["api_sync_error"] = "Senha temporaria de sincronizacao ausente."
            continue

        user["api_sync_status"] = "syncing"
        user["api_sync_error"] = ""
        save_users(users)

        if status_callback:
            status_callback("syncing", user)

        try:
            payload = create_remote_user(public_user(user), password)
            api_user_id = _remote_user_field(payload, "id", "userId")
            api_company_id = _remote_user_field(payload, "companyId", "company_id")

            if not api_user_id:
                raise ValueError("API nao retornou o ID do usuario.")

            user["api_user_id"] = api_user_id
            user["api_company_id"] = api_company_id or user.get("company_id", DEFAULT_COMPANY_ID)
            user["company_id"] = user["api_company_id"]
            user["api_sync_status"] = "synced"
            user["api_sync_error"] = ""
            user["api_synced_at"] = datetime.now().isoformat(timespec="seconds")
            user.pop("api_sync_password", None)
            synced += 1

            if status_callback:
                status_callback("synced", user)
        except Exception as error:
            user["api_sync_status"] = "failed"
            user["api_sync_error"] = str(error)[:180]

            if status_callback:
                status_callback("failed", user)

    save_users(users)
    return synced


def count_pending_api_users():
    return sum(
        1
        for user in load_users()
        if user.get("api_sync_status") in API_SYNC_PENDING_STATUSES
    )


def change_user_password(username, old_password, new_password):
    normalized_username = normalize_username(username)
    users = load_users()

    for user in users:
        if user.get("username") != normalized_username:
            continue

        validate_user_payload(normalized_username, new_password, user.get("role"))

        if not verify_password(old_password, user.get("password", {})):
            raise ValueError("Senha atual incorreta.")

        if crypto_service.is_crypto_available():
            if not user_has_crypto_metadata(user):
                attach_new_crypto_metadata(user, old_password)

            master_key = crypto_service.decrypt_user_master_key(old_password, user)
            user.update(crypto_service.reencrypt_user_master_key(master_key, new_password))
            user["_session_master_key"] = crypto_service.b64encode(master_key)

        user["password"] = hash_password(new_password)
        user["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_users(users)
        return public_user(user)

    raise ValueError("Usuario nao encontrado.")


def reset_password_with_recovery(username, recovery_key, new_password):
    normalized_username = normalize_username(username)
    users = load_users()

    for user in users:
        if user.get("username") != normalized_username:
            continue

        validate_user_payload(normalized_username, new_password, user.get("role"))

        if not user.get("recovery_key_enabled"):
            raise ValueError("Este usuario nao possui chave de recuperacao.")

        metadata, master_key = crypto_service.reset_user_password_with_recovery(
            recovery_key,
            new_password,
            user,
        )
        user.update(metadata)
        user["password"] = hash_password(new_password)
        user["updated_at"] = datetime.now().isoformat(timespec="seconds")
        user["_session_master_key"] = crypto_service.b64encode(master_key)
        save_users(users)
        return public_user(user)

    raise ValueError("Usuario nao encontrado.")


def update_user(username, role=None, name=None, password=None):
    normalized_username = normalize_username(username)
    users = load_users()

    for user in users:
        if user.get("username") != normalized_username:
            continue

        next_role = role if role is not None else user.get("role")
        validate_user_payload(normalized_username, password, next_role)

        admin_count = sum(1 for current_user in users if current_user.get("role") == "admin")

        if user.get("role") == "admin" and next_role != "admin" and admin_count <= 1:
            raise ValueError("Nao e possivel alterar o perfil do ultimo administrador.")

        if role is not None:
            user["role"] = role

        if name is not None:
            next_name = name.strip() or normalized_username
            normalized_next_name = normalize_name(next_name)

            for current_user in users:
                if current_user.get("username") == normalized_username:
                    continue

                if normalize_name(current_user.get("name")) == normalized_next_name:
                    raise ValueError("Ja existe um usuario com esse nome de exibicao.")

            user["name"] = next_name

        if password:
            if crypto_service.is_crypto_available():
                if user_has_crypto_metadata(user):
                    user["crypto_reset_without_old_password"] = True

                attach_new_crypto_metadata(user, password)

            user["password"] = hash_password(password)

        user["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_users(users)
        return public_user(user)

    raise ValueError("Usuario nao encontrado.")


def delete_user(username):
    normalized_username = normalize_username(username)
    users = load_users()
    remaining_users = [
        user for user in users if user.get("username") != normalized_username
    ]

    if len(remaining_users) == len(users):
        raise ValueError("Usuario nao encontrado.")

    admin_count = sum(1 for user in users if user.get("role") == "admin")
    removed_user = next(
        user for user in users if user.get("username") == normalized_username
    )

    if removed_user.get("role") == "admin" and admin_count <= 1:
        raise ValueError("Nao e possivel remover o ultimo administrador.")

    save_users(remaining_users)


def list_api_company_users(current_user=None):
    token = (current_user or {}).get("auth_token")
    company_id = (current_user or {}).get("company_id")

    if not token:
        return []

    try:
        if API_LIST_USERS_CLIENT is not None:
            return [
                public_api_user(
                    {
                        "id": user.get("id") or user.get("userId"),
                        "email": user.get("email") or user.get("username"),
                        "name": user.get("name"),
                        "role": user.get("role"),
                        "company_id": (
                            user.get("companyId")
                            or user.get("company_id")
                            or (current_user or {}).get("company_id")
                        ),
                        "created_at": user.get("createdAt") or user.get("created_at"),
                    }
                )
                for user in API_LIST_USERS_CLIENT(token)
                if isinstance(user, dict)
            ]

        from auth import api_client

        if not api_client.is_configured():
            return list_local_api_company_users(company_id)

        users = api_client.list_company_users(token)

        if users:
            return users

        return list_local_api_company_users(company_id)
    except Exception:
        return list_local_api_company_users(company_id)


def list_local_api_company_users(company_id):
    if not company_id:
        return []

    try:
        from api.database import connect, rows_to_dicts

        connection = connect()

        try:
            rows = connection.execute(
                """
                SELECT id, company_id, name, email, role, status, created_at, updated_at
                FROM users
                WHERE company_id = ?
                ORDER BY status ASC, LOWER(name) ASC
                """,
                (company_id,),
            ).fetchall()
            users = []

            for user in rows_to_dicts(rows):
                public_data = public_api_user(user)

                if public_data:
                    users.append(public_data)

            return users
        finally:
            connection.close()
    except Exception:
        return []


def list_public_users(current_user=None):
    users_by_username = {}

    for user in list_api_company_users(current_user):
        if user and user.get("username"):
            users_by_username[user["username"]] = user

    current_company_id = (current_user or {}).get("company_id")

    for user in load_users():
        if current_company_id and user.get("company_id", DEFAULT_COMPANY_ID) != current_company_id:
            continue

        public_data = public_user(user)

        if not public_data or not public_data.get("username"):
            continue

        users_by_username.setdefault(public_data["username"], public_data)

    return list(users_by_username.values())
