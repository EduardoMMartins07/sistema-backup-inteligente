import base64
import os
import secrets
import string


KDF_ALGORITHM = "pbkdf2-sha256"
ENCRYPTION_ALGORITHM = "AES-256-GCM"
KDF_ITERATIONS = 390000
KEY_SIZE = 32
SALT_SIZE = 16
NONCE_SIZE = 12
RECOVERY_GROUPS = 4
RECOVERY_GROUP_SIZE = 4


class CryptoDependencyError(RuntimeError):
    pass


class CryptoError(RuntimeError):
    pass


def _load_crypto_primitives():
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError as error:
        raise CryptoDependencyError(
            "Instale a dependencia 'cryptography' para usar backups criptografados."
        ) from error

    return AESGCM, InvalidTag, hashes, PBKDF2HMAC


def is_crypto_available():
    try:
        _load_crypto_primitives()
    except CryptoDependencyError:
        return False
    return True


def b64encode(data):
    return base64.b64encode(data).decode("ascii")


def b64decode(value):
    return base64.b64decode(value.encode("ascii"))


def generate_salt(size=SALT_SIZE):
    return secrets.token_bytes(size)


def generate_key(size=KEY_SIZE):
    return secrets.token_bytes(size)


def derive_key_from_password(password, salt, iterations=KDF_ITERATIONS):
    _, _, hashes, PBKDF2HMAC = _load_crypto_primitives()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=int(iterations),
    )
    return kdf.derive(str(password).encode("utf-8"))


def encrypt_bytes(key, plaintext, associated_data=None):
    AESGCM, _, _, _ = _load_crypto_primitives()
    nonce = secrets.token_bytes(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return {
        "nonce": nonce,
        "ciphertext": ciphertext,
    }


def decrypt_bytes(key, nonce, ciphertext, associated_data=None):
    AESGCM, InvalidTag, _, _ = _load_crypto_primitives()

    try:
        return AESGCM(key).decrypt(nonce, ciphertext, associated_data)
    except InvalidTag as error:
        raise CryptoError("Falha ao descriptografar: senha, chave ou dados invalidos.") from error


def encrypt_file(input_path, output_path, key, associated_data=None):
    with open(input_path, "rb") as source_file:
        plaintext = source_file.read()

    encrypted = encrypt_bytes(key, plaintext, associated_data)
    target_directory = os.path.dirname(output_path)

    if target_directory:
        os.makedirs(target_directory, exist_ok=True)

    with open(output_path, "wb") as target_file:
        target_file.write(encrypted["ciphertext"])

    return {
        "file_nonce": b64encode(encrypted["nonce"]),
        "auth_tag": "included_in_ciphertext",
    }


def decrypt_file(input_path, output_path, key, file_nonce, associated_data=None):
    with open(input_path, "rb") as source_file:
        ciphertext = source_file.read()

    plaintext = decrypt_bytes(
        key,
        b64decode(file_nonce),
        ciphertext,
        associated_data,
    )
    target_directory = os.path.dirname(output_path)

    if target_directory:
        os.makedirs(target_directory, exist_ok=True)

    with open(output_path, "wb") as target_file:
        target_file.write(plaintext)


def encrypt_key(wrapping_key, raw_key, associated_data=None):
    encrypted = encrypt_bytes(wrapping_key, raw_key, associated_data)
    return {
        "encrypted_key": b64encode(encrypted["ciphertext"]),
        "key_nonce": b64encode(encrypted["nonce"]),
    }


def decrypt_key(wrapping_key, encrypted_key, key_nonce, associated_data=None):
    return decrypt_bytes(
        wrapping_key,
        b64decode(key_nonce),
        b64decode(encrypted_key),
        associated_data,
    )


def generate_recovery_key():
    alphabet = string.ascii_uppercase + string.digits
    groups = [
        "".join(secrets.choice(alphabet) for _ in range(RECOVERY_GROUP_SIZE))
        for _ in range(RECOVERY_GROUPS)
    ]
    return "RECOVERY-" + "-".join(groups)


def create_user_crypto_metadata(password, enable_recovery=True):
    salt = generate_salt()
    password_key = derive_key_from_password(password, salt)
    master_key = generate_key()
    encrypted_master = encrypt_key(password_key, master_key, b"user-master-key")
    metadata = {
        "kdf_algorithm": KDF_ALGORITHM,
        "kdf_salt": b64encode(salt),
        "kdf_iterations": KDF_ITERATIONS,
        "encrypted_master_key": encrypted_master["encrypted_key"],
        "master_key_nonce": encrypted_master["key_nonce"],
        "recovery_key_enabled": False,
    }
    recovery_key = None

    if enable_recovery:
        recovery_key = generate_recovery_key()
        recovery_salt = generate_salt()
        recovery_wrapping_key = derive_key_from_password(
            recovery_key,
            recovery_salt,
            KDF_ITERATIONS,
        )
        encrypted_recovery_master = encrypt_key(
            recovery_wrapping_key,
            master_key,
            b"user-master-key-recovery",
        )
        metadata.update(
            {
                "recovery_key_enabled": True,
                "recovery_kdf_salt": b64encode(recovery_salt),
                "encrypted_master_key_recovery": encrypted_recovery_master["encrypted_key"],
                "recovery_key_nonce": encrypted_recovery_master["key_nonce"],
            }
        )

    return metadata, master_key, recovery_key


def decrypt_user_master_key(password, user_record):
    salt = b64decode(user_record["kdf_salt"])
    iterations = int(user_record.get("kdf_iterations", KDF_ITERATIONS))
    password_key = derive_key_from_password(password, salt, iterations)
    return decrypt_key(
        password_key,
        user_record["encrypted_master_key"],
        user_record["master_key_nonce"],
        b"user-master-key",
    )


def reencrypt_user_master_key(master_key, new_password):
    salt = generate_salt()
    password_key = derive_key_from_password(new_password, salt)
    encrypted_master = encrypt_key(password_key, master_key, b"user-master-key")
    return {
        "kdf_algorithm": KDF_ALGORITHM,
        "kdf_salt": b64encode(salt),
        "kdf_iterations": KDF_ITERATIONS,
        "encrypted_master_key": encrypted_master["encrypted_key"],
        "master_key_nonce": encrypted_master["key_nonce"],
    }


def reset_user_password_with_recovery(recovery_key, new_password, user_record):
    recovery_salt = b64decode(user_record["recovery_kdf_salt"])
    recovery_wrapping_key = derive_key_from_password(
        recovery_key,
        recovery_salt,
        int(user_record.get("kdf_iterations", KDF_ITERATIONS)),
    )
    master_key = decrypt_key(
        recovery_wrapping_key,
        user_record["encrypted_master_key_recovery"],
        user_record["recovery_key_nonce"],
        b"user-master-key-recovery",
    )
    return reencrypt_user_master_key(master_key, new_password), master_key
