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
    return bool(load_users())


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
    users = load_users()
    user = None

    for current_user in users:
        if current_user.get("username") == normalized_username:
            user = current_user
            break

    if not user:
        return None

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


def create_user(username, password, role, name=None):
    normalized_username = validate_user_payload(username, password, role)
    users = load_users()
    display_name = name.strip() if name and name.strip() else normalized_username
    normalized_display_name = normalize_name(display_name)

    if any(user.get("username") == normalized_username for user in users):
        raise ValueError("Ja existe esse usuario cadastrado.")

    if any(normalize_name(user.get("name")) == normalized_display_name for user in users):
        raise ValueError("Ja existe um usuario com esse nome de exibicao.")

    now = datetime.now().isoformat(timespec="seconds")
    user = {
        "username": normalized_username,
        "name": display_name,
        "role": role,
        "company_id": DEFAULT_COMPANY_ID,
        "password": hash_password(password),
        "created_at": now,
        "updated_at": now,
    }

    if crypto_service.is_crypto_available():
        attach_new_crypto_metadata(user, password)

    users.append(user)
    save_users(users)
    return public_user(user)


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


def list_public_users():
    return [public_user(user) for user in load_users()]
