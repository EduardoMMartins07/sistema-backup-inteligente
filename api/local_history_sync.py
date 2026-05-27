import json
import os
import platform
import re

from api.database import connect, utc_now
from api.services import audit_log, build_storage_key


def _safe_id(value, prefix):
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")

    if not text:
        text = "unknown"

    return f"{prefix}_{text[:80]}"


def _json_dumps(data):
    if data is None:
        data = {}

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _load_json_file(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return default

    return data if isinstance(data, type(default)) else default


def _find_api_user(db, entry):
    username = str(entry.get("user") or "").strip().lower()
    company_id = entry.get("company_id") or "default"

    if not username:
        return None

    row = db.execute(
        """
        SELECT *
        FROM users
        WHERE email = ? AND company_id = ? AND status = 'ACTIVE'
        """,
        (username, company_id),
    ).fetchone()
    return dict(row) if row else None


def _ensure_local_device(db, user):
    now = utc_now()
    identifier = f"desktop-local-{user['id']}"
    row = db.execute(
        """
        SELECT *
        FROM devices
        WHERE company_id = ? AND user_id = ? AND identifier = ?
        """,
        (user["company_id"], user["id"], identifier),
    ).fetchone()

    if row:
        db.execute(
            "UPDATE devices SET last_seen_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
        return dict(row)

    device = {
        "id": _safe_id(user["id"], "device_local"),
        "company_id": user["company_id"],
        "user_id": user["id"],
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
        ON CONFLICT(id) DO NOTHING
        """,
        device,
    )
    return device


def _ensure_local_folder(db, user, device, entry):
    now = utc_now()
    path = (
        entry.get("backup_base_destination")
        or entry.get("backup_user_directory")
        or entry.get("backup_storage")
        or "Desktop local"
    )
    folder_id = _safe_id(f"{device['id']}_{path}", "folder_local")
    row = db.execute(
        """
        SELECT *
        FROM monitored_folders
        WHERE id = ? AND company_id = ?
        """,
        (folder_id, user["company_id"]),
    ).fetchone()

    if row:
        db.execute(
            "UPDATE monitored_folders SET updated_at = ? WHERE id = ?",
            (now, folder_id),
        )
        return dict(row)

    folder = {
        "id": folder_id,
        "company_id": user["company_id"],
        "user_id": user["id"],
        "device_id": device["id"],
        "path": str(path),
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
        ON CONFLICT(id) DO NOTHING
        """,
        folder,
    )
    return folder


def _sync_desktop_cache_files(db, user, device):
    now = utc_now()
    device_id = device.get("id", "")
    config = _load_json_file(os.path.join("config", "config.json"), {})
    history = _load_json_file(os.path.join("config", "backup_history.json"), [])
    config_id = _safe_id(f"{user['id']}_{device_id}", "desktop_config")
    history_id = _safe_id(f"{user['id']}_{device_id}", "desktop_history")

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
            user["company_id"],
            user["id"],
            device_id,
            _json_dumps(config),
            now,
            now,
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
            user["company_id"],
            user["id"],
            device_id,
            _json_dumps(history[-50:]),
            now,
            now,
        ),
    )


def _backup_status(entry):
    status = str(entry.get("status") or "").strip().lower()

    if status == "failed":
        return "FAILED"

    if status == "cancelled":
        return "CANCELED"

    if status == "completed":
        return "SUCCESS"

    return "RUNNING"


def _backup_type(entry):
    if entry.get("history_group_type") == "priority_snapshot":
        return "SNAPSHOT"

    return "INCREMENTAL"


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


def _backup_name(entry):
    return (
        entry.get("backup_name")
        or entry.get("backup_file")
        or entry.get("snapshot_id")
        or "Backup local"
    )


def sync_history_entry(entry):
    if not isinstance(entry, dict):
        return False

    snapshot_id = entry.get("snapshot_id") or os.path.splitext(
        os.path.basename(entry.get("snapshot_path") or entry.get("backup_path") or "")
    )[0]

    if not snapshot_id:
        return False

    db = connect()

    try:
        user = _find_api_user(db, entry)

        if not user:
            return False

        device = _ensure_local_device(db, user)
        folder = _ensure_local_folder(db, user, device, entry)
        backup_id = _safe_id(snapshot_id, "backup_local")
        now = utc_now()
        created_at = entry.get("started_at") or now
        finished_at = entry.get("finished_at")
        s3_key = (
            entry.get("cloud_snapshot_key")
            or build_storage_key(
                user["company_id"],
                user["id"],
                device["id"],
                folder["id"],
                backup_id,
                os.path.basename(entry.get("snapshot_path") or "snapshot.json"),
            )
        )
        metadata = {
            "source": "desktop_history",
            "snapshotPath": entry.get("snapshot_path"),
            "backupPath": entry.get("backup_path"),
            "cloudSyncStatus": entry.get("cloud_sync_status"),
            "cloudStoragePrefix": entry.get("cloud_storage_prefix"),
            "trigger": entry.get("trigger"),
            "storageMode": entry.get("storage_mode"),
            "items": _snapshot_items_from_history(entry),
        }
        payload = {
            "id": backup_id,
            "company_id": user["company_id"],
            "user_id": user["id"],
            "device_id": device["id"],
            "folder_id": folder["id"],
            "name": _backup_name(entry),
            "type": _backup_type(entry),
            "status": _backup_status(entry),
            "priority": "NORMAL",
            "size_bytes": int(entry.get("compacted_size_bytes") or 0),
            "file_count": int(entry.get("total_files") or 0),
            "s3_key": s3_key,
            "checksum": "",
            "error_message": entry.get("error_message") or "",
            "metadata_json": _json_dumps(metadata),
            "local_path": entry.get("snapshot_path") or entry.get("backup_path") or "",
            "started_at": created_at,
            "finished_at": finished_at,
            "created_at": created_at,
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
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                size_bytes = excluded.size_bytes,
                file_count = excluded.file_count,
                s3_key = excluded.s3_key,
                error_message = excluded.error_message,
                metadata_json = excluded.metadata_json,
                local_path = excluded.local_path,
                finished_at = excluded.finished_at,
                updated_at = excluded.updated_at
            """,
            payload,
        )

        snapshot_path = entry.get("snapshot_path") or entry.get("backup_path")

        if snapshot_path and payload["type"] == "SNAPSHOT":
            snapshot_id_for_api = _safe_id(snapshot_id, "snapshot_local")
            db.execute(
                """
                INSERT INTO snapshots (
                    id, company_id, user_id, device_id, folder_id, backup_id, name,
                    s3_key, size_bytes, file_count, checksum, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    s3_key = excluded.s3_key,
                    size_bytes = excluded.size_bytes,
                    file_count = excluded.file_count
                """,
                (
                    snapshot_id_for_api,
                    user["company_id"],
                    user["id"],
                    device["id"],
                    folder["id"],
                    backup_id,
                    os.path.basename(snapshot_path),
                    s3_key,
                    int(entry.get("compacted_size_bytes") or 0),
                    int(entry.get("total_files") or 0),
                    "",
                    created_at,
                ),
            )

        _sync_desktop_cache_files(db, user, device)
        audit_log(
            db,
            user["company_id"],
            user["id"],
            "BACKUP_FINISHED" if payload["status"] == "SUCCESS" else "BACKUP_FAILED",
            f"Backup desktop sincronizado: {payload['name']}",
            {"backupId": backup_id, "source": "desktop_history"},
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()


def sync_history_file(path=os.path.join("config", "backup_history.json")):
    if not os.path.exists(path):
        return 0

    try:
        with open(path, "r", encoding="utf-8") as file:
            history = json.load(file)
    except (OSError, json.JSONDecodeError):
        return 0

    if not isinstance(history, list):
        return 0

    synced = 0

    for entry in history:
        if sync_history_entry(entry):
            synced += 1

    return synced
