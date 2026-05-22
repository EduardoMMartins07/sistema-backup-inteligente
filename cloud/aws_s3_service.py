import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from security import crypto_service


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLOUD_SETTINGS_PATH = os.path.join(PROJECT_ROOT, "config", "cloud_settings.json")
CLOUD_SECRET_KEY_PATH = os.path.join(PROJECT_ROOT, "config", "cloud_secret.key")
AWS_PROVIDER = "AWS S3"
DEFAULT_BASE_PREFIX = "backups"
SECRET_ASSOCIATED_DATA = b"aws-s3-secret-access-key"
SECRET_MASK = "************"
STATUS_DISABLED = "desativado"
STATUS_SYNCING = "sincronizando"
STATUS_SYNCED = "sincronizado"
STATUS_FAILED = "falhou"
STATUS_NOT_SYNCED = "nao_sincronizado"


class CloudStorageError(RuntimeError):
    pass


class CloudPermissionError(PermissionError):
    pass


def require_cloud_admin(user):
    from auth.permissions import can

    if not can(user, "manage_cloud_connection"):
        raise CloudPermissionError(
            "Seu perfil nao tem permissao para configurar a nuvem."
        )


def _load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return default

    return data if isinstance(data, type(default)) else default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def normalize_s3_segment(value, fallback="default"):
    text = str(value or "").strip().replace("\\", "/")
    parts = [part for part in text.split("/") if part not in ("", ".", "..")]
    text = "_".join(parts) if parts else ""
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-/")
    return text or fallback


def normalize_s3_prefix(prefix):
    prefix = str(prefix or DEFAULT_BASE_PREFIX).replace("\\", "/")
    parts = [
        normalize_s3_segment(part, fallback="")
        for part in prefix.split("/")
        if part not in ("", ".", "..")
    ]
    parts = [part for part in parts if part]
    return "/".join(parts) or DEFAULT_BASE_PREFIX


def normalize_s3_relative_path(relative_path):
    text = str(relative_path or "").replace("\\", "/")
    parts = [
        normalize_s3_segment(part, fallback="")
        for part in text.split("/")
        if part not in ("", ".", "..")
    ]
    return "/".join(part for part in parts if part)


def build_s3_key(
    company_id,
    user_id,
    backup_date,
    relative_path,
    base_prefix=DEFAULT_BASE_PREFIX
):
    prefix = normalize_s3_prefix(base_prefix)
    company = normalize_s3_segment(company_id)
    user = normalize_s3_segment(user_id)
    date = normalize_s3_segment(backup_date)
    remote_relative = normalize_s3_relative_path(relative_path)
    parts = [prefix, company, user, date]

    if remote_relative:
        parts.append(remote_relative)

    return "/".join(parts)


def build_s3_user_key(
    company_id,
    user_id,
    relative_path,
    base_prefix=DEFAULT_BASE_PREFIX
):
    prefix = normalize_s3_prefix(base_prefix)
    company = normalize_s3_segment(company_id)
    user = normalize_s3_segment(user_id)
    remote_relative = normalize_s3_relative_path(relative_path)
    parts = [prefix, company, user]

    if remote_relative:
        parts.append(remote_relative)

    return "/".join(parts)


def get_default_cloud_settings():
    return {
        "provider": AWS_PROVIDER,
        "enabled": False,
        "bucket_name": "",
        "region": "",
        "base_prefix": DEFAULT_BASE_PREFIX,
        "endpoint_url": "",
        "access_key_id": "",
        "secret_access_key_encrypted": "",
        "secret_access_key_nonce": "",
        "last_test_status": "",
        "last_test_at": "",
        "last_test_message": "",
    }


def normalize_cloud_settings(settings):
    normalized = get_default_cloud_settings()

    if isinstance(settings, dict):
        normalized.update(
            {
                key: value
                for key, value in settings.items()
                if key in normalized
            }
        )

        if "secret_access_key" in settings:
            normalized["secret_access_key"] = settings.get("secret_access_key", "")

    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["provider"] = AWS_PROVIDER
    normalized["bucket_name"] = str(normalized.get("bucket_name", "")).strip()
    normalized["region"] = str(normalized.get("region", "")).strip()
    normalized["base_prefix"] = normalize_s3_prefix(normalized.get("base_prefix"))
    normalized["endpoint_url"] = str(normalized.get("endpoint_url", "")).strip()
    normalized["access_key_id"] = str(normalized.get("access_key_id", "")).strip()
    return normalized


def load_secret_key():
    if os.path.exists(CLOUD_SECRET_KEY_PATH):
        with open(CLOUD_SECRET_KEY_PATH, "r", encoding="utf-8") as file:
            value = file.read().strip()

        if value:
            return crypto_service.b64decode(value)

    key = crypto_service.generate_key()
    os.makedirs(os.path.dirname(CLOUD_SECRET_KEY_PATH), exist_ok=True)

    with open(CLOUD_SECRET_KEY_PATH, "w", encoding="utf-8") as file:
        file.write(crypto_service.b64encode(key))

    return key


def encrypt_secret(secret):
    encrypted = crypto_service.encrypt_bytes(
        load_secret_key(),
        str(secret).encode("utf-8"),
        SECRET_ASSOCIATED_DATA,
    )
    return {
        "secret_access_key_encrypted": crypto_service.b64encode(
            encrypted["ciphertext"]
        ),
        "secret_access_key_nonce": crypto_service.b64encode(encrypted["nonce"]),
    }


def decrypt_secret(settings):
    encrypted_value = settings.get("secret_access_key_encrypted")
    nonce = settings.get("secret_access_key_nonce")

    if not encrypted_value or not nonce:
        return ""

    plaintext = crypto_service.decrypt_bytes(
        load_secret_key(),
        crypto_service.b64decode(nonce),
        crypto_service.b64decode(encrypted_value),
        SECRET_ASSOCIATED_DATA,
    )
    return plaintext.decode("utf-8")


def load_cloud_settings(include_secret=False):
    settings = normalize_cloud_settings(
        _load_json(CLOUD_SETTINGS_PATH, get_default_cloud_settings())
    )

    if include_secret:
        settings["secret_access_key"] = decrypt_secret(settings)

    return settings


def save_cloud_settings(settings):
    current = load_cloud_settings()
    next_settings = normalize_cloud_settings({**current, **(settings or {})})
    secret = str((settings or {}).get("secret_access_key", ""))

    if secret:
        next_settings.update(encrypt_secret(secret))
    else:
        next_settings["secret_access_key_encrypted"] = current.get(
            "secret_access_key_encrypted",
            "",
        )
        next_settings["secret_access_key_nonce"] = current.get(
            "secret_access_key_nonce",
            "",
        )

    next_settings.pop("secret_access_key", None)
    _save_json(CLOUD_SETTINGS_PATH, next_settings)
    return next_settings


def save_cloud_settings_for_user(user, settings):
    require_cloud_admin(user)
    return save_cloud_settings(settings)


def test_s3_connection_for_user(user, settings=None, client=None, now=None):
    require_cloud_admin(user)
    return test_s3_connection(settings=settings, client=client, now=now)


def mask_secret_configured(settings=None):
    settings = settings or load_cloud_settings()
    return SECRET_MASK if settings.get("secret_access_key_encrypted") else ""


def mask_access_key(access_key_id):
    value = str(access_key_id or "")

    if len(value) <= 4:
        return value

    return f"{value[:4]}{'*' * max(4, len(value) - 4)}"


def get_public_cloud_settings():
    settings = load_cloud_settings()
    public = {
        key: value
        for key, value in settings.items()
        if key not in {"secret_access_key_encrypted", "secret_access_key_nonce"}
    }
    public["access_key_id_masked"] = mask_access_key(settings.get("access_key_id"))
    public["secret_access_key_masked"] = mask_secret_configured(settings)
    return public


def create_s3_client(settings=None):
    settings = settings or load_cloud_settings(include_secret=True)

    try:
        import boto3
    except ImportError as error:
        raise CloudStorageError(
            "Dependencia boto3 nao instalada para conexao AWS S3."
        ) from error

    kwargs = {
        "service_name": "s3",
        "region_name": settings.get("region") or None,
        "aws_access_key_id": settings.get("access_key_id") or None,
        "aws_secret_access_key": settings.get("secret_access_key") or None,
    }

    if settings.get("endpoint_url"):
        kwargs["endpoint_url"] = settings["endpoint_url"]

    return boto3.client(**kwargs)


def get_s3_client(settings=None, client=None):
    return client or create_s3_client(settings)


def sanitize_cloud_error(error):
    message = str(error or "").strip()
    known_markers = (
        "AccessDenied",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "NoSuchBucket",
        "NoSuchKey",
        "EndpointConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
    )

    for marker in known_markers:
        if marker.lower() in message.lower():
            return marker

    sensitive_words = ("secret", "token", "password", "credential", "key")

    if any(word in message.lower() for word in sensitive_words):
        return "Falha de acesso ao AWS S3."

    return message[:180] or error.__class__.__name__


def build_test_object_key(settings, now=None):
    now = now or datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S")
    return f"{normalize_s3_prefix(settings.get('base_prefix'))}/_connection_test/{timestamp}.txt"


def test_s3_connection(settings=None, client=None, now=None):
    settings = normalize_cloud_settings(settings or load_cloud_settings(include_secret=True))
    bucket = settings.get("bucket_name")

    if not bucket:
        return {
            "success": False,
            "status": STATUS_FAILED,
            "message": "Bucket nao informado.",
        }

    test_key = build_test_object_key(settings, now=now)

    try:
        s3_client = get_s3_client(settings, client)
        s3_client.head_bucket(Bucket=bucket)
        s3_client.put_object(Bucket=bucket, Key=test_key, Body=b"smart-backup-test")
        s3_client.delete_object(Bucket=bucket, Key=test_key)
    except Exception as error:
        return {
            "success": False,
            "status": STATUS_FAILED,
            "message": sanitize_cloud_error(error),
        }

    return {
        "success": True,
        "status": "ok",
        "message": (
            "Conexao com AWS S3 realizada com sucesso. "
            "Bucket acessivel. Permissao de upload validada."
        ),
    }


def parse_backup_date(history_entry):
    timestamp = str(history_entry.get("timestamp", "")).strip()

    for date_format in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(timestamp, date_format).strftime("%Y-%m-%d")
        except ValueError:
            pass

    for key in ("snapshot_path", "backup_path"):
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", str(history_entry.get(key, "")))

        if match:
            return match.group(1)

    return datetime.now().strftime("%Y-%m-%d")


def strip_backup_date_from_relative_path(relative_path, backup_date):
    normalized = normalize_s3_relative_path(relative_path)
    prefix = f"{backup_date}/"

    if normalized == backup_date:
        return ""

    if normalized.startswith(prefix):
        return normalized[len(prefix):]

    return normalized


def get_history_entry_scope(history_entry):
    return {
        "company_id": history_entry.get("company_id") or "default",
        "user_id": history_entry.get("user") or history_entry.get("username") or "sistema",
        "backup_date": parse_backup_date(history_entry),
    }


def build_cloud_storage_prefix(history_entry, settings):
    scope = get_history_entry_scope(history_entry)
    key = build_s3_key(
        scope["company_id"],
        scope["user_id"],
        scope["backup_date"],
        "",
        base_prefix=settings.get("base_prefix"),
    )
    return f"{key}/"


def get_disabled_cloud_result():
    return {
        "cloud_provider": AWS_PROVIDER,
        "cloud_bucket": "",
        "cloud_snapshot_key": "",
        "cloud_storage_prefix": "",
        "cloud_sync_status": STATUS_DISABLED,
        "cloud_synced_at": "",
        "cloud_error_message": "",
    }


def build_failure_result(history_entry, settings, error):
    return {
        "cloud_provider": AWS_PROVIDER,
        "cloud_bucket": settings.get("bucket_name", ""),
        "cloud_snapshot_key": "",
        "cloud_storage_prefix": build_cloud_storage_prefix(history_entry, settings),
        "cloud_sync_status": STATUS_FAILED,
        "cloud_synced_at": "",
        "cloud_error_message": sanitize_cloud_error(error),
    }


def resolve_local_object_path(storage_root, object_path):
    relative = normalize_s3_relative_path(object_path)
    return os.path.join(storage_root, *relative.split("/"))


def iter_incremental_object_paths(history_entry, snapshot):
    seen = set()
    files = snapshot.get("files") if isinstance(snapshot, dict) else []

    if isinstance(files, list):
        for file_data in files:
            object_path = file_data.get("object_path", "")

            if object_path and object_path not in seen:
                seen.add(object_path)
                yield object_path

    file_snapshot = history_entry.get("file_snapshot", {})

    if isinstance(file_snapshot, dict):
        for file_data in file_snapshot.values():
            object_path = file_data.get("object_path", "")

            if object_path and object_path not in seen:
                seen.add(object_path)
                yield object_path


def should_upload_incremental_object(file_data):
    status = str(file_data.get("status", "")).strip()

    if not status:
        return True

    return status == "stored_new_object"


def iter_incremental_upload_object_paths(history_entry, snapshot):
    seen = set()
    files = snapshot.get("files") if isinstance(snapshot, dict) else []

    if isinstance(files, list):
        for file_data in files:
            if not should_upload_incremental_object(file_data):
                continue

            object_path = file_data.get("object_path", "")

            if object_path and object_path not in seen:
                seen.add(object_path)
                yield object_path

    if seen:
        return

    file_snapshot = history_entry.get("file_snapshot", {})

    if isinstance(file_snapshot, dict):
        for file_data in file_snapshot.values():
            if not should_upload_incremental_object(file_data):
                continue

            object_path = file_data.get("object_path", "")

            if object_path and object_path not in seen:
                seen.add(object_path)
                yield object_path


def get_cloud_upload_worker_count(total_uploads):
    if total_uploads <= 1:
        return 1

    available_cpus = os.cpu_count() or 2
    return min(8, total_uploads, max(2, available_cpus * 2))


def upload_file(client, bucket, local_path, key):
    client.upload_file(str(local_path), bucket, key)


def download_file(client, bucket, key, local_path):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    client.download_file(bucket, key, str(local_path))


def delete_file(client, bucket, key):
    client.delete_object(Bucket=bucket, Key=key)


def file_exists(client, bucket, key):
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def list_user_backups(company_id, user_id, settings=None, client=None):
    settings = normalize_cloud_settings(settings or load_cloud_settings(include_secret=True))
    s3_client = get_s3_client(settings, client)
    prefix = build_s3_user_key(
        company_id,
        user_id,
        "",
        base_prefix=settings.get("base_prefix"),
    )
    response = s3_client.list_objects_v2(
        Bucket=settings.get("bucket_name"),
        Prefix=f"{prefix}/",
    )
    return [
        item.get("Key")
        for item in response.get("Contents", [])
        if item.get("Key")
    ]


def sync_backup_to_s3(history_entry, settings=None, client=None, progress_callback=None):
    settings = normalize_cloud_settings(settings or load_cloud_settings(include_secret=True))

    if not settings.get("enabled"):
        if progress_callback:
            progress_callback(0, 0, "Sincronizacao com AWS S3 desativada.")
        return get_disabled_cloud_result()

    bucket = settings.get("bucket_name")
    snapshot_path = history_entry.get("snapshot_path") or history_entry.get("backup_path")
    storage_root = history_entry.get("backup_storage", "")
    index_path = history_entry.get("index_path") or (
        os.path.join(storage_root, "index.json") if storage_root else ""
    )

    if not bucket:
        return build_failure_result(history_entry, settings, ValueError("Bucket nao informado."))

    if not snapshot_path or not os.path.exists(snapshot_path):
        return build_failure_result(
            history_entry,
            settings,
            FileNotFoundError("Snapshot local nao encontrado."),
        )

    snapshot = _load_json(snapshot_path, {})
    storage_root = storage_root or snapshot.get("storage_root", "")
    scope = get_history_entry_scope(history_entry)
    upload_plan = []
    snapshot_key = build_s3_key(
        scope["company_id"],
        scope["user_id"],
        scope["backup_date"],
        f"snapshots/{os.path.basename(snapshot_path)}",
        base_prefix=settings.get("base_prefix"),
    )
    upload_plan.append((snapshot_path, snapshot_key))

    if index_path and os.path.exists(index_path):
        upload_plan.append(
            (
                index_path,
                build_s3_user_key(
                    scope["company_id"],
                    scope["user_id"],
                    "index.json",
                    base_prefix=settings.get("base_prefix"),
                ),
            )
        )

    for object_path in iter_incremental_upload_object_paths(history_entry, snapshot):
        if not storage_root:
            continue

        object_abs_path = resolve_local_object_path(storage_root, object_path)

        if not os.path.exists(object_abs_path):
            return build_failure_result(
                history_entry,
                settings,
                FileNotFoundError("Objeto local nao encontrado."),
            )

        object_relative = strip_backup_date_from_relative_path(
            object_path,
            scope["backup_date"],
        )
        upload_plan.append(
            (
                object_abs_path,
                build_s3_key(
                    scope["company_id"],
                    scope["user_id"],
                    scope["backup_date"],
                    object_relative,
                    base_prefix=settings.get("base_prefix"),
                ),
            )
        )

    try:
        s3_client = get_s3_client(settings, client)
        total_uploads = len(upload_plan)

        if progress_callback:
            progress_callback(0, total_uploads, "Preparando envio para AWS S3...")

        worker_count = get_cloud_upload_worker_count(total_uploads)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_upload = {
                executor.submit(upload_file, s3_client, bucket, local_path, key): (
                    local_path,
                    key,
                )
                for local_path, key in upload_plan
            }

            for upload_index, future in enumerate(as_completed(future_to_upload), start=1):
                future.result()

                if progress_callback:
                    progress_callback(
                        upload_index,
                        total_uploads,
                        f"Enviando para AWS S3: {upload_index}/{total_uploads}",
                    )
    except Exception as error:
        return build_failure_result(history_entry, settings, error)

    return {
        "cloud_provider": AWS_PROVIDER,
        "cloud_bucket": bucket,
        "cloud_snapshot_key": snapshot_key,
        "cloud_storage_prefix": build_cloud_storage_prefix(history_entry, settings),
        "cloud_sync_status": STATUS_SYNCED,
        "cloud_synced_at": datetime.now().isoformat(timespec="seconds"),
        "cloud_error_message": "",
    }


def download_backup_from_s3(history_entry, settings=None, client=None):
    settings = normalize_cloud_settings(settings or load_cloud_settings(include_secret=True))

    if not settings.get("enabled"):
        return get_disabled_cloud_result()

    bucket = settings.get("bucket_name") or history_entry.get("cloud_bucket", "")

    if history_entry.get("cloud_sync_status") != STATUS_SYNCED:
        return build_failure_result(
            history_entry,
            settings,
            ValueError("Backup nao sincronizado com a nuvem."),
        )

    if not bucket:
        return build_failure_result(history_entry, settings, ValueError("Bucket nao informado."))

    scope = get_history_entry_scope(history_entry)
    snapshot_path = history_entry.get("snapshot_path") or history_entry.get("backup_path")
    snapshot_key = history_entry.get("cloud_snapshot_key") or build_s3_key(
        scope["company_id"],
        scope["user_id"],
        scope["backup_date"],
        f"snapshots/{os.path.basename(snapshot_path)}",
        base_prefix=settings.get("base_prefix"),
    )

    try:
        s3_client = get_s3_client(settings, client)

        if snapshot_path and not os.path.exists(snapshot_path):
            download_file(s3_client, bucket, snapshot_key, snapshot_path)

        snapshot = _load_json(snapshot_path, {})
        storage_root = history_entry.get("backup_storage") or snapshot.get("storage_root", "")
        index_path = history_entry.get("index_path") or (
            os.path.join(storage_root, "index.json") if storage_root else ""
        )

        if index_path and not os.path.exists(index_path):
            download_file(
                s3_client,
                bucket,
                build_s3_user_key(
                    scope["company_id"],
                    scope["user_id"],
                    "index.json",
                    base_prefix=settings.get("base_prefix"),
                ),
                index_path,
            )

        for object_path in iter_incremental_object_paths(history_entry, snapshot):
            object_abs_path = resolve_local_object_path(storage_root, object_path)

            if os.path.exists(object_abs_path):
                continue

            object_relative = strip_backup_date_from_relative_path(
                object_path,
                scope["backup_date"],
            )
            object_key = build_s3_key(
                scope["company_id"],
                scope["user_id"],
                scope["backup_date"],
                object_relative,
                base_prefix=settings.get("base_prefix"),
            )
            download_file(s3_client, bucket, object_key, object_abs_path)
    except Exception as error:
        return build_failure_result(history_entry, settings, error)

    return {
        "cloud_provider": AWS_PROVIDER,
        "cloud_bucket": bucket,
        "cloud_snapshot_key": snapshot_key,
        "cloud_storage_prefix": build_cloud_storage_prefix(history_entry, settings),
        "cloud_sync_status": STATUS_SYNCED,
        "cloud_synced_at": history_entry.get("cloud_synced_at", ""),
        "cloud_error_message": "",
    }
