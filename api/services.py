import json
import os
import platform
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, status

from api.config import get_settings
from api.database import row_to_dict, rows_to_dicts, utc_now
from api.security import create_password_hash, new_id, normalize_role, verify_password
from api.storage import enforce_upload_size


BACKUP_TYPES = {"FULL", "INCREMENTAL", "SNAPSHOT"}
BACKUP_STATUS = {"PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELED"}
BACKUP_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "NORMAL"}
SNAPSHOT_EVENT = "SNAPSHOT_CREATED"
RECENT_BACKUP_WINDOW_HOURS = 72


def require_found(resource, message="Recurso nao encontrado."):
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)

    return resource


def json_dumps(data):
    if data is None:
        data = {}

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def json_loads(value, default=None):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return {} if default is None else default


def normalize_email(email):
    return str(email or "").strip().lower()


def public_user(user):
    if not user:
        return None

    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "companyId": user["company_id"],
        "status": user.get("status", "ACTIVE"),
        "createdAt": user.get("created_at"),
        "updatedAt": user.get("updated_at"),
    }


def public_company(company):
    if not company:
        return None

    return {
        "id": company["id"],
        "name": company["name"],
        "status": company["status"],
        "createdAt": company["created_at"],
        "updatedAt": company["updated_at"],
    }


def users_count(db):
    return db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]


def company_users_count(db, company_id):
    return db.execute(
        "SELECT COUNT(*) AS total FROM users WHERE company_id = ? AND status = 'ACTIVE'",
        (company_id,),
    ).fetchone()["total"]


def get_user_by_id(db, user_id, company_id=None, active_only=True):
    where = ["id = ?"]
    params = [user_id]

    if company_id is not None:
        where.append("company_id = ?")
        params.append(company_id)

    if active_only:
        where.append("status = 'ACTIVE'")

    row = db.execute(
        f"SELECT * FROM users WHERE {' AND '.join(where)}",
        params,
    ).fetchone()
    return row_to_dict(row)


def get_user_by_email(db, email):
    row = db.execute(
        "SELECT * FROM users WHERE email = ? AND status = 'ACTIVE'",
        (normalize_email(email),),
    ).fetchone()
    return row_to_dict(row)


def get_company_by_id(db, company_id):
    row = db.execute(
        "SELECT * FROM companies WHERE id = ?",
        (company_id,),
    ).fetchone()
    return row_to_dict(row)


def create_company(db, name, company_id=None):
    now = utc_now()
    company = {
        "id": company_id or new_id("company"),
        "name": str(name or "").strip() or "Empresa",
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
    }
    db.execute(
        """
        INSERT INTO companies (id, name, status, created_at, updated_at)
        VALUES (:id, :name, :status, :created_at, :updated_at)
        """,
        company,
    )
    return company


def create_user(db, company_id, name, email, password, role):
    email = normalize_email(email)
    role = normalize_role(role)

    if len(email) < 5 or "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalido.")

    if not password or len(str(password)) < 6:
        raise HTTPException(status_code=400, detail="Senha deve ter ao menos 6 caracteres.")

    now = utc_now()
    user = {
        "id": new_id("user"),
        "company_id": company_id,
        "name": str(name or "").strip() or email,
        "email": email,
        "password_hash": create_password_hash(password),
        "role": role,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
    }

    try:
        db.execute(
            """
            INSERT INTO users (
                id, company_id, name, email, password_hash, role, status,
                created_at, updated_at
            )
            VALUES (
                :id, :company_id, :name, :email, :password_hash, :role, :status,
                :created_at, :updated_at
            )
            """,
            user,
        )
    except Exception as error:
        if "UNIQUE" in str(error).upper():
            raise HTTPException(status_code=400, detail="Email ja cadastrado.") from error
        raise

    audit_log(db, company_id, None, "USER_CREATED", f"Usuario criado: {email}", {
        "userId": user["id"],
        "role": role,
    })
    return user


def authenticate_user(db, email, password):
    user = get_user_by_email(db, email)

    if not user or not verify_password(password, user.get("password_hash")):
        return None

    audit_log(db, user["company_id"], user["id"], "USER_LOGIN", "Login realizado.", {})
    return user


def create_first_admin(db, company_name, name, email, password):
    if users_count(db) > 0:
        raise HTTPException(status_code=409, detail="Administrador inicial ja existe.")

    company, user = create_company_with_admin(db, company_name, name, email, password)
    db.commit()
    return company, user


def create_company_with_admin(db, company_name, name, email, password):
    company = create_company(db, company_name)
    user = create_user(
        db,
        company["id"],
        name,
        email,
        password,
        "ADMIN_EMPRESA",
    )
    audit_log(
        db,
        company["id"],
        user["id"],
        "COMPANY_CREATED",
        f"Empresa criada: {company['name']}",
        {"companyId": company["id"]},
    )
    return company, user


def list_company_users(db, company_id):
    return rows_to_dicts(
        db.execute(
            """
            SELECT id, company_id, name, email, role, status, created_at, updated_at
            FROM users
            WHERE company_id = ?
            ORDER BY status ASC, LOWER(name) ASC
            """,
            (company_id,),
        ).fetchall()
    )


def update_company_user(db, company_id, user_id, name=None, role=None, status_value=None):
    user = require_found(get_user_by_id(db, user_id, company_id=company_id, active_only=False))
    next_name = str(name or user["name"]).strip() or user["email"]
    next_role = normalize_role(role or user["role"])
    next_status = str(status_value or user["status"]).strip().upper()

    if next_status not in {"ACTIVE", "DISABLED"}:
        raise HTTPException(status_code=400, detail="Status invalido.")

    if user["role"] == "ADMIN_EMPRESA" and (
        next_role != "ADMIN_EMPRESA" or next_status != "ACTIVE"
    ):
        active_admins = db.execute(
            """
            SELECT COUNT(*) AS total
            FROM users
            WHERE company_id = ? AND role = 'ADMIN_EMPRESA' AND status = 'ACTIVE'
            """,
            (company_id,),
        ).fetchone()["total"]

        if active_admins <= 1:
            raise HTTPException(
                status_code=400,
                detail="Nao e possivel desativar ou rebaixar o ultimo admin da empresa.",
            )

    now = utc_now()
    db.execute(
        """
        UPDATE users
        SET name = ?, role = ?, status = ?, updated_at = ?
        WHERE id = ? AND company_id = ?
        """,
        (next_name, next_role, next_status, now, user_id, company_id),
    )
    audit_log(db, company_id, user_id, "USER_UPDATED", f"Usuario atualizado: {user['email']}", {
        "role": next_role,
        "status": next_status,
    })
    db.commit()
    return get_user_by_id(db, user_id, company_id=company_id, active_only=False)


def disable_company_user(db, company_id, user_id):
    return update_company_user(db, company_id, user_id, status_value="DISABLED")


def audit_log(db, company_id, user_id, event, description, metadata=None):
    db.execute(
        """
        INSERT INTO audit_logs (
            id, company_id, user_id, event, description, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id("audit"),
            company_id,
            user_id,
            event,
            description,
            json_dumps(metadata or {}),
            utc_now(),
        ),
    )


def register_device(db, current_user, name, hostname, identifier):
    identifier = str(identifier or "").strip()

    if not identifier:
        raise HTTPException(status_code=400, detail="Identificador do dispositivo e obrigatorio.")

    now = utc_now()
    existing = db.execute(
        """
        SELECT * FROM devices
        WHERE company_id = ? AND user_id = ? AND identifier = ?
        """,
        (current_user["company_id"], current_user["id"], identifier),
    ).fetchone()

    if existing:
        db.execute(
            """
            UPDATE devices
            SET name = ?, hostname = ?, updated_at = ?, last_seen_at = ?
            WHERE id = ?
            """,
            (
                str(name or "").strip() or existing["name"],
                str(hostname or "").strip() or existing["hostname"],
                now,
                now,
                existing["id"],
            ),
        )
        db.commit()
        return row_to_dict(existing), "updated"

    device = {
        "id": new_id("device"),
        "company_id": current_user["company_id"],
        "user_id": current_user["id"],
        "name": str(name or "").strip() or "Dispositivo",
        "hostname": str(hostname or "").strip() or "unknown",
        "identifier": identifier,
        "created_at": now,
        "updated_at": now,
        "last_seen_at": now,
    }
    db.execute(
        """
        INSERT INTO devices (
            id, company_id, user_id, name, hostname, identifier,
            created_at, updated_at, last_seen_at
        )
        VALUES (
            :id, :company_id, :user_id, :name, :hostname, :identifier,
            :created_at, :updated_at, :last_seen_at
        )
        """,
        device,
    )
    audit_log(db, current_user["company_id"], current_user["id"], "DEVICE_REGISTERED", device["name"], {
        "deviceId": device["id"],
    })
    db.commit()
    return device, "registered"


def get_device_for_user_action(db, current_user, device_id):
    row = db.execute(
        "SELECT * FROM devices WHERE id = ? AND company_id = ?",
        (device_id, current_user["company_id"]),
    ).fetchone()
    device = require_found(row_to_dict(row), "Dispositivo nao encontrado.")

    if current_user["role"] != "ADMIN_EMPRESA" and device["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Dispositivo nao pertence ao usuario.")

    return device


def create_monitored_folder(db, current_user, device_id, path, alias):
    device = get_device_for_user_action(db, current_user, device_id)
    now = utc_now()
    folder = {
        "id": new_id("folder"),
        "company_id": current_user["company_id"],
        "user_id": device["user_id"],
        "device_id": device["id"],
        "path": str(path or "").strip(),
        "alias": str(alias or "").strip(),
        "active": 1,
        "created_at": now,
        "updated_at": now,
    }

    if not folder["path"]:
        raise HTTPException(status_code=400, detail="Caminho da pasta e obrigatorio.")

    if not folder["alias"]:
        folder["alias"] = folder["path"]

    db.execute(
        """
        INSERT INTO monitored_folders (
            id, company_id, user_id, device_id, path, alias, active, created_at, updated_at
        )
        VALUES (
            :id, :company_id, :user_id, :device_id, :path, :alias, :active,
            :created_at, :updated_at
        )
        """,
        folder,
    )
    audit_log(db, current_user["company_id"], current_user["id"], "FOLDER_REGISTERED", folder["path"], {
        "folderId": folder["id"],
        "deviceId": device["id"],
    })
    db.commit()
    return folder


def get_folder_for_backup(db, current_user, folder_id, device_id):
    row = db.execute(
        """
        SELECT * FROM monitored_folders
        WHERE id = ? AND device_id = ? AND company_id = ? AND active = 1
        """,
        (folder_id, device_id, current_user["company_id"]),
    ).fetchone()
    folder = require_found(row_to_dict(row), "Pasta monitorada nao encontrada.")

    if current_user["role"] != "ADMIN_EMPRESA" and folder["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Pasta nao pertence ao usuario.")

    return folder


def build_storage_key(company_id, user_id, device_id, folder_id, backup_id, filename="backup.zip"):
    settings = get_settings()
    parts = [
        settings.base_s3_prefix.strip("/"),
        company_id,
        user_id,
        device_id,
        folder_id,
        backup_id,
        filename,
    ]
    return "/".join(str(part).strip("/").replace("\\", "_") for part in parts if part)


def normalize_backup_status(value):
    normalized = str(value or "RUNNING").strip().upper()
    aliases = {
        "COMPLETED": "SUCCESS",
        "CONCLUIDO": "SUCCESS",
        "CANCELLED": "CANCELED",
        "CANCELADO": "CANCELED",
        "FALHOU": "FAILED",
        "SUCESSO": "SUCCESS",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized not in BACKUP_STATUS:
        raise HTTPException(status_code=400, detail="Status de backup invalido.")

    return normalized


def normalize_backup_type(value):
    normalized = str(value or "INCREMENTAL").strip().upper()
    aliases = {
        "FULL_BACKUP": "FULL",
        "COMPLETO": "FULL",
        "INCREMENTAL_BACKUP": "INCREMENTAL",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized not in BACKUP_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de backup invalido.")

    return normalized


def normalize_backup_priority(value):
    normalized = str(value or "NORMAL").strip().upper()
    aliases = {
        "BAIXA": "LOW",
        "MEDIA": "MEDIUM",
        "ALTA": "HIGH",
        "MIXED": "NORMAL",
        "MISTA": "NORMAL",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized not in BACKUP_PRIORITIES:
        normalized = "NORMAL"

    return normalized


def payload_value(payload, *names, default=None):
    for name in names:
        value = getattr(payload, name, None)

        if value is not None and value != "":
            return value

    return default


def total_size_from_items(items):
    total = 0

    for item in items or []:
        if not isinstance(item, dict):
            continue

        try:
            total += int(item.get("size_bytes") or item.get("size") or 0)
        except (TypeError, ValueError):
            continue

    return total


def ensure_metadata_device(db, current_user):
    now = utc_now()
    identifier = f"desktop-metadata-{current_user['id']}"
    row = db.execute(
        """
        SELECT *
        FROM devices
        WHERE company_id = ? AND user_id = ? AND identifier = ?
        """,
        (current_user["company_id"], current_user["id"], identifier),
    ).fetchone()

    if row:
        db.execute(
            "UPDATE devices SET last_seen_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
        return row_to_dict(row)

    device = {
        "id": new_id("device"),
        "company_id": current_user["company_id"],
        "user_id": current_user["id"],
        "name": "Desktop local",
        "hostname": platform.node() or "localhost",
        "identifier": identifier,
        "created_at": now,
        "updated_at": now,
        "last_seen_at": now,
    }
    db.execute(
        """
        INSERT INTO devices (
            id, company_id, user_id, name, hostname, identifier,
            created_at, updated_at, last_seen_at
        )
        VALUES (
            :id, :company_id, :user_id, :name, :hostname, :identifier,
            :created_at, :updated_at, :last_seen_at
        )
        """,
        device,
    )
    return device


def ensure_metadata_folder(db, current_user, device, payload):
    now = utc_now()
    path = str(
        payload_value(
            payload,
            "local_path",
            "localPath",
            "remote_path",
            "remotePath",
            default="Desktop local",
        )
        or "Desktop local"
    )
    row = db.execute(
        """
        SELECT *
        FROM monitored_folders
        WHERE company_id = ? AND user_id = ? AND device_id = ? AND path = ?
        """,
        (current_user["company_id"], current_user["id"], device["id"], path),
    ).fetchone()

    if row:
        db.execute(
            "UPDATE monitored_folders SET updated_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        return row_to_dict(row)

    folder = {
        "id": new_id("folder"),
        "company_id": current_user["company_id"],
        "user_id": current_user["id"],
        "device_id": device["id"],
        "path": path,
        "alias": "Backup local desktop",
        "active": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.execute(
        """
        INSERT INTO monitored_folders (
            id, company_id, user_id, device_id, path, alias, active, created_at, updated_at
        )
        VALUES (
            :id, :company_id, :user_id, :device_id, :path, :alias, :active,
            :created_at, :updated_at
        )
        """,
        folder,
    )
    return folder


def create_backup_from_metadata(db, current_user, payload):
    company_id = payload_value(payload, "company_id", "companyId")

    if company_id and company_id != current_user["company_id"]:
        raise HTTPException(status_code=403, detail="Empresa do backup nao confere com o token.")

    user_id = payload_value(payload, "user_id", "userId")

    if user_id and user_id not in {current_user["id"], current_user.get("email")}:
        raise HTTPException(status_code=403, detail="Usuario do backup nao confere com o token.")

    device = ensure_metadata_device(db, current_user)
    folder = ensure_metadata_folder(db, current_user, device, payload)
    backup_id = str(payload_value(payload, "backup_id", "backupId", default="")).strip() or new_id("backup")
    backup_type = normalize_backup_type(payload_value(payload, "backup_type", "backupType", "type"))
    status_value = normalize_backup_status(payload_value(payload, "status", default="RUNNING"))
    priority = normalize_backup_priority(payload_value(payload, "priority"))
    created_at = payload_value(payload, "created_at", "createdAt", "started_at", "startedAt", default=utc_now())
    finished_at = payload_value(payload, "finished_at", "finishedAt")
    file_count = int(payload_value(payload, "file_count", "fileCount", default=0) or 0)
    remote_path = str(payload_value(payload, "remote_path", "remotePath", default="") or "")
    storage_target = str(payload_value(payload, "storage_target", "storageTarget", default="local") or "local")
    metadata = payload.metadata if isinstance(payload.metadata, dict) else {}
    items = payload.items or []
    size_bytes = int(payload_value(payload, "total_size_bytes", "totalSizeBytes", "sizeBytes", default=0) or 0)

    if size_bytes <= 0:
        size_bytes = total_size_from_items(items)

    metadata.update({
        "externalBackupId": backup_id,
        "storageTarget": storage_target,
        "remotePath": remote_path,
        "items": items,
        "userName": payload_value(payload, "user_name", "userName", default=current_user.get("name")),
    })
    backup = {
        "id": backup_id,
        "company_id": current_user["company_id"],
        "user_id": current_user["id"],
        "device_id": device["id"],
        "folder_id": folder["id"],
        "name": str(payload_value(payload, "backup_name", "backupName", "name", default=backup_id) or backup_id),
        "type": backup_type,
        "status": status_value,
        "priority": priority,
        "size_bytes": size_bytes,
        "file_count": file_count,
        "s3_key": remote_path or build_storage_key(
            current_user["company_id"],
            current_user["id"],
            device["id"],
            folder["id"],
            backup_id,
        ),
        "checksum": "",
        "error_message": "",
        "metadata_json": json_dumps(metadata),
        "local_path": str(payload_value(payload, "local_path", "localPath", default="") or ""),
        "started_at": created_at,
        "finished_at": finished_at,
        "created_at": created_at,
        "updated_at": utc_now(),
    }
    db.execute(
        """
        INSERT INTO backups (
            id, company_id, user_id, device_id, folder_id, name, type, status,
            priority, size_bytes, file_count, s3_key, checksum, error_message,
            metadata_json, local_path, started_at, finished_at, created_at, updated_at
        )
        VALUES (
            :id, :company_id, :user_id, :device_id, :folder_id, :name, :type, :status,
            :priority, :size_bytes, :file_count, :s3_key, :checksum, :error_message,
            :metadata_json, :local_path, :started_at, :finished_at, :created_at, :updated_at
        )
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            priority = excluded.priority,
            size_bytes = excluded.size_bytes,
            file_count = excluded.file_count,
            s3_key = excluded.s3_key,
            metadata_json = excluded.metadata_json,
            local_path = excluded.local_path,
            finished_at = excluded.finished_at,
            updated_at = excluded.updated_at
        """,
        backup,
    )
    audit_log(
        db,
        current_user["company_id"],
        current_user["id"],
        "BACKUP_METADATA_SYNCED",
        backup["name"],
        {"backupId": backup_id, "storageTarget": storage_target},
    )
    db.commit()
    return get_backup_for_user_action(db, current_user, backup_id)


def create_backup(db, current_user, payload):
    device = get_device_for_user_action(db, current_user, payload.deviceId)
    folder = get_folder_for_backup(db, current_user, payload.folderId, device["id"])

    if device["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Backup deve ser criado pelo dono do dispositivo.")

    backup_type = str(payload.type or "INCREMENTAL").upper()
    status_value = str(getattr(payload, "status", None) or "RUNNING").upper()
    priority = str(payload.priority or "NORMAL").upper()

    if backup_type not in BACKUP_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de backup invalido.")

    if status_value not in BACKUP_STATUS:
        raise HTTPException(status_code=400, detail="Status de backup invalido.")

    if priority not in BACKUP_PRIORITIES:
        raise HTTPException(status_code=400, detail="Prioridade invalida.")

    now = utc_now()
    backup_id = new_id("backup")
    s3_key = build_storage_key(
        current_user["company_id"],
        current_user["id"],
        device["id"],
        folder["id"],
        backup_id,
    )
    backup = {
        "id": backup_id,
        "company_id": current_user["company_id"],
        "user_id": current_user["id"],
        "device_id": device["id"],
        "folder_id": folder["id"],
        "name": str(payload.name or "").strip() or backup_id,
        "type": backup_type,
        "status": status_value,
        "priority": priority,
        "size_bytes": int(payload.sizeBytes or 0),
        "file_count": int(payload.fileCount or 0),
        "s3_key": s3_key,
        "checksum": str(payload.checksum or ""),
        "error_message": "",
        "metadata_json": json_dumps(payload.metadata or {}),
        "local_path": "",
        "started_at": now,
        "finished_at": None,
        "created_at": now,
        "updated_at": now,
    }
    db.execute(
        """
        INSERT INTO backups (
            id, company_id, user_id, device_id, folder_id, name, type, status,
            priority, size_bytes, file_count, s3_key, checksum, error_message,
            metadata_json, local_path, started_at, finished_at, created_at, updated_at
        )
        VALUES (
            :id, :company_id, :user_id, :device_id, :folder_id, :name, :type, :status,
            :priority, :size_bytes, :file_count, :s3_key, :checksum, :error_message,
            :metadata_json, :local_path, :started_at, :finished_at, :created_at, :updated_at
        )
        """,
        backup,
    )
    audit_log(db, current_user["company_id"], current_user["id"], "BACKUP_STARTED", backup["name"], {
        "backupId": backup_id,
        "deviceId": device["id"],
        "folderId": folder["id"],
    })
    db.commit()
    return backup


def get_backup_for_user_action(db, current_user, backup_id, mutate=False):
    row = db.execute(
        "SELECT * FROM backups WHERE id = ? AND company_id = ?",
        (backup_id, current_user["company_id"]),
    ).fetchone()
    backup = require_found(row_to_dict(row), "Backup nao encontrado.")

    if current_user["role"] != "ADMIN_EMPRESA" and backup["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Backup nao pertence ao usuario.")

    if current_user["role"] == "VIEWER" and mutate:
        raise HTTPException(status_code=403, detail="Visualizador nao pode alterar backups.")

    if mutate and current_user["role"] == "ADMIN_EMPRESA" and backup["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Admin nao finaliza backup de outro usuario.")

    return backup


def get_backup_detail(db, current_user, backup_id):
    backup = get_backup_for_user_action(db, current_user, backup_id)
    backup["metadata"] = json_loads(backup.pop("metadata_json", "{}"))
    backup["snapshots"] = list_snapshots(db, current_user, backup_id=backup_id)
    backup["snapshot_files"] = list_backup_snapshot_files(backup)
    return backup


def snapshot_file_candidates(backup):
    metadata = backup.get("metadata") if isinstance(backup.get("metadata"), dict) else {}

    for path_value in (
        backup.get("local_path"),
        metadata.get("snapshotPath"),
        metadata.get("backupPath"),
    ):
        if path_value:
            yield Path(path_value)


def list_backup_snapshot_files(backup):
    metadata = backup.get("metadata") if isinstance(backup.get("metadata"), dict) else {}
    metadata_items = metadata.get("items") or metadata.get("snapshotFiles")

    if isinstance(metadata_items, list) and metadata_items:
        return [
            format_snapshot_file_for_web(file_data)
            for file_data in metadata_items
            if isinstance(file_data, dict)
        ]

    for snapshot_path in snapshot_file_candidates(backup):
        try:
            if not snapshot_path.exists() or not snapshot_path.is_file():
                continue

            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        files = snapshot.get("files") if isinstance(snapshot, dict) else None

        if not isinstance(files, list):
            continue

        return [
            format_snapshot_file_for_web(file_data)
            for file_data in files
            if isinstance(file_data, dict)
        ]

    return []


def format_snapshot_file_for_web(file_data):
    archive_name = str(
        file_data.get("archive_name")
        or file_data.get("path")
        or file_data.get("object_path")
        or ""
    ).replace("\\", "/")
    file_name = (
        file_data.get("file_name")
        or file_data.get("name")
        or os.path.basename(archive_name)
        or "-"
    )

    return {
        "name": file_name,
        "archive_name": archive_name or "-",
        "size_bytes": parse_snapshot_file_size(file_data),
        "status": snapshot_file_status_label(file_data.get("status")),
    }


def parse_snapshot_file_size(file_data):
    try:
        return int(file_data.get("size_bytes") or file_data.get("size") or 0)
    except (TypeError, ValueError):
        return 0


def snapshot_file_status_label(status_value):
    labels = {
        "stored_new_object": "Novo objeto",
        "referenced_existing_object": "Objeto existente",
        "skipped_unchanged": "Sem alteracao",
        "skipped_not_eligible": "Nao elegivel",
        "error": "Erro",
    }
    normalized = str(status_value or "").strip()
    return labels.get(normalized, normalized or "-")


def save_backup_upload(db, current_user, backup_id, upload_file):
    backup = get_backup_for_user_action(db, current_user, backup_id, mutate=True)
    storage_root = Path(get_settings().storage_root)
    max_bytes = enforce_upload_size(backup.get("size_bytes") or 0)
    filename = Path(upload_file.filename or "backup.zip").name or "backup.zip"
    target_path = (
        storage_root
        / current_user["company_id"]
        / backup["user_id"]
        / backup["id"]
        / filename
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    with target_path.open("wb") as destination:
        while True:
            chunk = upload_file.file.read(1024 * 1024)

            if not chunk:
                break

            written += len(chunk)

            if written > max_bytes:
                destination.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Arquivo excede o limite de {get_settings().max_upload_size_mb} MB.",
                )

            destination.write(chunk)

    size_bytes = target_path.stat().st_size
    db.execute(
        """
        UPDATE backups
        SET local_path = ?, size_bytes = CASE WHEN size_bytes = 0 THEN ? ELSE size_bytes END,
            updated_at = ?
        WHERE id = ? AND company_id = ?
        """,
        (str(target_path), size_bytes, utc_now(), backup_id, current_user["company_id"]),
    )
    db.commit()
    backup["local_path"] = str(target_path)
    backup["uploadedBytes"] = size_bytes
    return backup


def finish_backup(db, current_user, backup_id, payload):
    backup = get_backup_for_user_action(db, current_user, backup_id, mutate=True)
    status_value = str(payload.status or "").upper()

    if status_value not in {"SUCCESS", "FAILED", "CANCELED"}:
        raise HTTPException(status_code=400, detail="Status final invalido.")

    finished_at = payload.finishedAt or utc_now()
    s3_key = str(payload.s3Key or backup["s3_key"])
    error_message = str(payload.errorMessage or "")
    db.execute(
        """
        UPDATE backups
        SET status = ?, finished_at = ?, s3_key = ?, error_message = ?, updated_at = ?
        WHERE id = ? AND company_id = ?
        """,
        (
            status_value,
            finished_at,
            s3_key,
            error_message,
            utc_now(),
            backup_id,
            current_user["company_id"],
        ),
    )
    event = "BACKUP_FINISHED" if status_value == "SUCCESS" else "BACKUP_FAILED"
    audit_log(db, current_user["company_id"], current_user["id"], event, backup["name"], {
        "backupId": backup_id,
        "status": status_value,
        "errorMessage": error_message,
    })
    db.commit()
    return get_backup_for_user_action(db, current_user, backup_id)


def build_backup_filters(query, params, filters):
    if filters.get("userId"):
        query.append("b.user_id = ?")
        params.append(filters["userId"])

    if filters.get("deviceId"):
        query.append("b.device_id = ?")
        params.append(filters["deviceId"])

    if filters.get("folderId"):
        query.append("b.folder_id = ?")
        params.append(filters["folderId"])

    if filters.get("status"):
        query.append("b.status = ?")
        params.append(str(filters["status"]).upper())

    if filters.get("type"):
        query.append("b.type = ?")
        params.append(str(filters["type"]).upper())

    if filters.get("priority"):
        query.append("b.priority = ?")
        params.append(str(filters["priority"]).upper())

    if filters.get("startDate"):
        query.append("b.created_at >= ?")
        params.append(filters["startDate"])

    if filters.get("endDate"):
        query.append("b.created_at <= ?")
        params.append(filters["endDate"])


def list_backups(db, current_user, filters=None, limit=200):
    filters = filters or {}
    where = ["b.company_id = ?"]
    params = [current_user["company_id"]]

    if current_user["role"] != "ADMIN_EMPRESA":
        where.append("b.user_id = ?")
        params.append(current_user["id"])

    build_backup_filters(where, params, filters)
    rows = db.execute(
        f"""
        SELECT
            b.*,
            u.name AS user_name,
            d.name AS device_name,
            f.path AS folder_path
        FROM backups b
        JOIN users u ON u.id = b.user_id
        JOIN devices d ON d.id = b.device_id
        JOIN monitored_folders f ON f.id = b.folder_id
        WHERE {' AND '.join(where)}
        ORDER BY b.created_at DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    backups = rows_to_dicts(rows)

    for backup in backups:
        backup["metadata"] = json_loads(backup.pop("metadata_json", "{}"))

    return backups


def admin_dashboard(db, current_user):
    company = require_found(get_company_by_id(db, current_user["company_id"]))
    company_id = current_user["company_id"]
    summary_row = db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM users WHERE company_id = ? AND status = 'ACTIVE') AS users,
            (SELECT COUNT(*) FROM devices WHERE company_id = ?) AS devices,
            COUNT(*) AS backups,
            COALESCE(SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END), 0) AS successful_backups,
            COALESCE(SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END), 0) AS failed_backups,
            COALESCE(SUM(size_bytes), 0) AS total_size_bytes,
            MAX(CASE WHEN status = 'FAILED' THEN created_at ELSE NULL END) AS latest_failure_at
        FROM backups
        WHERE company_id = ?
        """,
        (company_id, company_id, company_id),
    ).fetchone()
    summary = {
        "users": summary_row["users"],
        "devices": summary_row["devices"],
        "backups": summary_row["backups"],
        "successfulBackups": summary_row["successful_backups"],
        "failedBackups": summary_row["failed_backups"],
        "totalSizeBytes": summary_row["total_size_bytes"],
        "latestFailureAt": summary_row["latest_failure_at"],
    }
    stale_threshold = (
        datetime.now(timezone.utc) - timedelta(hours=RECENT_BACKUP_WINDOW_HOURS)
    ).replace(microsecond=0).isoformat()
    summary["staleDevices"] = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM devices d
        WHERE d.company_id = ?
          AND NOT EXISTS (
              SELECT 1
              FROM backups b
              WHERE b.company_id = d.company_id
                AND b.device_id = d.id
                AND b.created_at >= ?
          )
        """,
        (company_id, stale_threshold),
    ).fetchone()["total"]
    summary["staleWindowHours"] = RECENT_BACKUP_WINDOW_HOURS
    total_backups = summary["backups"] or 0
    summary["successRate"] = round(
        (summary["successfulBackups"] / total_backups) * 100, 1
    ) if total_backups else 0
    recent = list_backups(db, current_user, limit=8)
    return {
        "company": public_company(company),
        "summary": summary,
        "recentBackups": recent,
    }


def list_devices(db, current_user):
    rows = db.execute(
        """
        SELECT d.*, u.name AS user_name, u.email AS user_email
        FROM devices d
        JOIN users u ON u.id = d.user_id
        WHERE d.company_id = ?
        ORDER BY d.last_seen_at DESC
        """,
        (current_user["company_id"],),
    ).fetchall()
    devices = rows_to_dicts(rows)
    folders_by_device = {device["id"]: [] for device in devices}

    if folders_by_device:
        placeholders = ", ".join("?" for _ in folders_by_device)
        folders = rows_to_dicts(
            db.execute(
                f"""
                SELECT *
                FROM monitored_folders
                WHERE company_id = ? AND device_id IN ({placeholders})
                ORDER BY LOWER(path)
                """,
                [current_user["company_id"], *folders_by_device.keys()],
            ).fetchall()
        )

        for folder in folders:
            folders_by_device.setdefault(folder["device_id"], []).append(folder)

    for device in devices:
        device["folders"] = folders_by_device.get(device["id"], [])

    return devices


def list_company_folders(db, current_user):
    return rows_to_dicts(
        db.execute(
            """
            SELECT f.*, d.name AS device_name, u.name AS user_name
            FROM monitored_folders f
            JOIN devices d ON d.id = f.device_id
            JOIN users u ON u.id = f.user_id
            WHERE f.company_id = ?
            ORDER BY f.updated_at DESC
            """,
            (current_user["company_id"],),
        ).fetchall()
    )


def _desktop_cache_device_id(device_id=None):
    return str(device_id or "").strip()


def get_desktop_config_cache(db, current_user, device_id=None):
    scope_device_id = _desktop_cache_device_id(device_id)
    config_row = db.execute(
        """
        SELECT config_json
        FROM desktop_configs
        WHERE company_id = ? AND user_id = ? AND device_id = ?
        """,
        (current_user["company_id"], current_user["id"], scope_device_id),
    ).fetchone()
    history_row = db.execute(
        """
        SELECT history_json
        FROM desktop_history
        WHERE company_id = ? AND user_id = ? AND device_id = ?
        """,
        (current_user["company_id"], current_user["id"], scope_device_id),
    ).fetchone()
    config = json_loads(config_row["config_json"], default={}) if config_row else {}
    history = json_loads(history_row["history_json"], default=[]) if history_row else []

    if not isinstance(config, dict):
        config = {}

    if not isinstance(history, list):
        history = []

    return {
        "config": config,
        "history": history,
        "deviceId": scope_device_id or None,
    }


def save_desktop_config_cache(db, current_user, config=None, history=None, device_id=None):
    scope_device_id = _desktop_cache_device_id(device_id)
    now = utc_now()
    config_payload = config if isinstance(config, dict) else {}
    history_payload = history if isinstance(history, list) else []
    config_id = new_id("desktop_config")
    history_id = new_id("desktop_history")
    scope = {
        "company_id": current_user["company_id"],
        "user_id": current_user["id"],
        "device_id": scope_device_id,
        "updated_at": now,
    }
    db.execute(
        """
        INSERT INTO desktop_configs (
            id, company_id, user_id, device_id, config_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_id, user_id, device_id) DO UPDATE SET
            config_json = excluded.config_json,
            updated_at = excluded.updated_at
        """,
        (
            config_id,
            scope["company_id"],
            scope["user_id"],
            scope["device_id"],
            json_dumps(config_payload),
            now,
            scope["updated_at"],
        ),
    )
    db.execute(
        """
        INSERT INTO desktop_history (
            id, company_id, user_id, device_id, history_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_id, user_id, device_id) DO UPDATE SET
            history_json = excluded.history_json,
            updated_at = excluded.updated_at
        """,
        (
            history_id,
            scope["company_id"],
            scope["user_id"],
            scope["device_id"],
            json_dumps(history_payload),
            now,
            scope["updated_at"],
        ),
    )
    audit_log(
        db,
        current_user["company_id"],
        current_user["id"],
        "DESKTOP_CONFIG_SYNCED",
        "Cache essencial do desktop sincronizado.",
        {"deviceId": scope_device_id},
    )
    db.commit()
    return get_desktop_config_cache(db, current_user, device_id=scope_device_id)


def validate_admin_company_resource(db, table, resource_id, company_id, message):
    allowed_tables = {
        "users": "users",
        "devices": "devices",
    }
    table_name = allowed_tables[table]
    row = db.execute(
        f"SELECT * FROM {table_name} WHERE id = ? AND company_id = ?",
        (resource_id, company_id),
    ).fetchone()
    return require_found(row_to_dict(row), message)


def list_user_backups(db, current_user, user_id, filters=None):
    validate_admin_company_resource(
        db,
        "users",
        user_id,
        current_user["company_id"],
        "Usuario nao encontrado.",
    )
    filters = dict(filters or {})
    filters["userId"] = user_id
    return list_backups(db, current_user, filters=filters)


def list_device_backups(db, current_user, device_id, filters=None):
    validate_admin_company_resource(
        db,
        "devices",
        device_id,
        current_user["company_id"],
        "Dispositivo nao encontrado.",
    )
    filters = dict(filters or {})
    filters["deviceId"] = device_id
    return list_backups(db, current_user, filters=filters)


def create_snapshot(db, current_user, payload):
    backup = get_backup_for_user_action(db, current_user, payload.backupId)
    snapshot_id = new_id("snapshot")
    s3_key = str(payload.s3Key or "").strip() or build_storage_key(
        backup["company_id"],
        backup["user_id"],
        backup["device_id"],
        backup["folder_id"],
        backup["id"],
        f"{snapshot_id}.json",
    )
    snapshot = {
        "id": snapshot_id,
        "company_id": backup["company_id"],
        "user_id": backup["user_id"],
        "device_id": backup["device_id"],
        "folder_id": backup["folder_id"],
        "backup_id": backup["id"],
        "name": str(payload.name or "").strip() or snapshot_id,
        "s3_key": s3_key,
        "size_bytes": int(payload.sizeBytes or 0),
        "file_count": int(payload.fileCount or 0),
        "checksum": str(payload.checksum or ""),
        "created_at": utc_now(),
    }
    db.execute(
        """
        INSERT INTO snapshots (
            id, company_id, user_id, device_id, folder_id, backup_id, name,
            s3_key, size_bytes, file_count, checksum, created_at
        )
        VALUES (
            :id, :company_id, :user_id, :device_id, :folder_id, :backup_id, :name,
            :s3_key, :size_bytes, :file_count, :checksum, :created_at
        )
        """,
        snapshot,
    )
    audit_log(db, backup["company_id"], current_user["id"], SNAPSHOT_EVENT, snapshot["name"], {
        "backupId": backup["id"],
        "snapshotId": snapshot_id,
    })
    db.commit()
    return snapshot


def list_snapshots(db, current_user, backup_id=None):
    where = ["s.company_id = ?"]
    params = [current_user["company_id"]]

    if current_user["role"] != "ADMIN_EMPRESA":
        where.append("s.user_id = ?")
        params.append(current_user["id"])

    if backup_id:
        where.append("s.backup_id = ?")
        params.append(backup_id)

    rows = db.execute(
        f"""
        SELECT s.*, b.name AS backup_name, b.type AS backup_type, u.name AS user_name, d.name AS device_name
        FROM snapshots s
        JOIN backups b ON b.id = s.backup_id
        JOIN users u ON u.id = s.user_id
        JOIN devices d ON d.id = s.device_id
        WHERE {' AND '.join(where)}
        ORDER BY s.created_at DESC
        """,
        params,
    ).fetchall()
    snapshots = rows_to_dicts(rows)

    return [
        snapshot
        for snapshot in snapshots
        if not (
            str(snapshot.get("id", "")).startswith("snapshot_local_")
            and snapshot.get("backup_type") != "SNAPSHOT"
        )
    ]


def list_audit_logs(db, current_user, filters=None, limit=200):
    filters = filters or {}
    where = ["a.company_id = ?"]
    params = [current_user["company_id"]]

    if filters.get("event"):
        where.append("a.event = ?")
        params.append(filters["event"])

    if filters.get("startDate"):
        where.append("a.created_at >= ?")
        params.append(filters["startDate"])

    if filters.get("endDate"):
        where.append("a.created_at <= ?")
        params.append(filters["endDate"])

    rows = db.execute(
        f"""
        SELECT a.*, u.name AS user_name, u.email AS user_email
        FROM audit_logs a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE {' AND '.join(where)}
        ORDER BY a.created_at DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    logs = rows_to_dicts(rows)

    for log in logs:
        log["metadata"] = json_loads(log.pop("metadata_json", "{}"))

    return logs


def ensure_storage_root():
    Path(get_settings().storage_root).mkdir(parents=True, exist_ok=True)
