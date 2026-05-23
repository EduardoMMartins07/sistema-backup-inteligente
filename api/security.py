import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from api.config import get_settings


PBKDF2_ITERATIONS = 260000
CANONICAL_ROLES = {"ADMIN_EMPRESA", "OPERADOR", "VIEWER"}
ROLE_COMPATIBILITY = {
    "admin": "ADMIN_EMPRESA",
    "administrator": "ADMIN_EMPRESA",
    "ADMIN": "ADMIN_EMPRESA",
    "operator": "OPERADOR",
    "OPERADOR": "OPERADOR",
    "viewer": "VIEWER",
    "visualizador": "VIEWER",
    "VIEWER": "VIEWER",
    "ADMIN_EMPRESA": "ADMIN_EMPRESA",
}


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def normalize_role(role):
    normalized = ROLE_COMPATIBILITY.get(str(role or "").strip())

    if normalized not in CANONICAL_ROLES:
        raise ValueError("Perfil invalido.")

    return normalized


def create_password_hash(password):
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(password_hash).decode("ascii"),
        ]
    )


def verify_password(password, stored_hash):
    try:
        algorithm, iterations, salt_b64, hash_b64 = str(stored_hash).split("$", 3)

        if algorithm != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            salt,
            int(iterations),
        )
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(actual, expected)


def create_access_token(user):
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {
        "sub": user["id"],
        "userId": user["id"],
        "companyId": user["company_id"],
        "role": user["role"],
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token):
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])

