import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime

from auth.permissions import ROLES

USERS_PATH = os.path.join("config", "users.json")
PBKDF2_ITERATIONS = 260000


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

    with open(USERS_PATH, "w", encoding="utf-8") as file:
        json.dump(users, file, indent=4, ensure_ascii=False)


def users_exist():
    return bool(load_users())


def normalize_username(username):
    return str(username or "").strip().lower()


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

    return {
        "username": user.get("username"),
        "name": user.get("name", user.get("username")),
        "role": user.get("role"),
        "created_at": user.get("created_at"),
    }


def authenticate(username, password):
    user = find_user(username)

    if not user:
        return None

    if not verify_password(password, user.get("password", {})):
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

    if any(user.get("username") == normalized_username for user in users):
        raise ValueError("Ja existe um usuario com esse nome.")

    now = datetime.now().isoformat(timespec="seconds")
    user = {
        "username": normalized_username,
        "name": name.strip() if name and name.strip() else normalized_username,
        "role": role,
        "password": hash_password(password),
        "created_at": now,
        "updated_at": now,
    }
    users.append(user)
    save_users(users)
    return public_user(user)


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
            user["name"] = name.strip() or normalized_username

        if password:
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
