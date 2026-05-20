import hashlib
import csv
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from datetime import datetime
from datetime import timedelta
import zstandard as zstd
from security import crypto_service
from utils.file_hash import calculate_file_hash

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "config.json")
DATASET_PATH = os.path.join(PROJECT_ROOT, "dataset", "files_dataset.csv")
DEFAULT_BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")
HISTORY_PATH = os.path.join(PROJECT_ROOT, "config", "backup_history.json")
SCHEDULE_PATH = os.path.join(PROJECT_ROOT, "config", "backup_schedule.json")
PRIORITY_STATE_PATH = os.path.join(PROJECT_ROOT, "config", "priority_backup_state.json")
ZIP_COMPRESSION_METHOD = zipfile.ZIP_LZMA
OBJECT_COMPRESSION_LEVEL = 9
RECOVERABLE_ACTIONS = {"alterado", "excluido"}
INCREMENTAL_STORAGE_DIRNAME = "backup_storage"
OBJECTS_DIRNAME = "arquivos_relacionados"
SNAPSHOTS_DIRNAME = "snapshots"
INDEX_FILENAME = "index.json"
INDEX_VERSION = 1
PRIORITY_LOW = "baixa"
PRIORITY_MEDIUM = "media"
PRIORITY_HIGH = "alta"
DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED = True
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
_BACKUP_ENV_FILE_LOADED = False
_ZSTD_THREAD_LOCAL = threading.local()
PRIORITY_INTERVALS = {
    PRIORITY_LOW: timedelta(days=7),
    PRIORITY_MEDIUM: timedelta(days=2),
    PRIORITY_HIGH: timedelta(hours=4),
}
DEV_PRIORITY_INTERVALS = {
    PRIORITY_LOW: timedelta(minutes=30),
    PRIORITY_MEDIUM: timedelta(minutes=15),
    PRIORITY_HIGH: timedelta(minutes=5),
}

INTERNAL_IGNORED_PATHS = [
    os.path.join(PROJECT_ROOT, "config"),
    os.path.join(PROJECT_ROOT, "dataset"),
    os.path.join(PROJECT_ROOT, ".git"),
    os.path.join(PROJECT_ROOT, "__pycache__"),
]


class BackupCancelledError(Exception):
    pass


def normalize_path(path):
    return os.path.abspath(os.path.normpath(path))


def resolve_configured_path(path):
    if not path:
        return DEFAULT_BACKUP_DIR

    if os.path.isabs(path):
        return normalize_path(path)

    return normalize_path(os.path.join(PROJECT_ROOT, path))


def is_subpath(path, parent):
    try:
        return os.path.commonpath([normalize_path(path), normalize_path(parent)]) == normalize_path(parent)
    except ValueError:
        return False


def load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return default

    return data if isinstance(data, type(default)) else default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def save_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f"{path}.tmp"

    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

    os.replace(temporary_path, path)


def load_backup_env_file(path=ENV_PATH):
    global _BACKUP_ENV_FILE_LOADED

    if _BACKUP_ENV_FILE_LOADED:
        return

    _BACKUP_ENV_FILE_LOADED = True

    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")

            if key and key not in os.environ:
                os.environ[key] = value


def load_config():
    return load_json(CONFIG_PATH, {})


def save_config(data):
    save_json(CONFIG_PATH, data)


def get_monitored_directories(config=None):
    config = config or load_config()
    directories = config.get("directories", [])
    return [directory for directory in directories if isinstance(directory, str) and directory.strip()]


def get_backup_destination(config=None):
    config = config or load_config()
    return resolve_configured_path(config.get("backup_destination"))


def sanitize_storage_segment(value, default="sistema"):
    segment = str(value or "").strip().lower()
    segment = re.sub(r"[^a-z0-9._-]+", "_", segment)
    segment = segment.strip("._-")
    return segment or default


def get_user_backup_destination(backup_destination=None, username=None):
    destination = resolve_configured_path(backup_destination or get_backup_destination())
    return os.path.join(destination, sanitize_storage_segment(username))


def is_deduplication_enabled(config=None):
    config = config or load_config()
    return bool(config.get("deduplicate_backup", False))


def is_priority_backup_policy_enabled(config=None):
    config = config or load_config()
    return bool(
        config.get(
            "priority_backup_policy_enabled",
            DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
        )
    )


def get_ignored_roots(config=None, backup_destination=None):
    ignored = [normalize_path(path) for path in INTERNAL_IGNORED_PATHS]
    ignored.append(normalize_path(backup_destination or get_backup_destination(config)))
    return ignored


def is_path_ignored(path, config=None, backup_destination=None):
    if not path:
        return False

    normalized_path = normalize_path(path)

    for ignored_root in get_ignored_roots(config, backup_destination):
        if is_subpath(normalized_path, ignored_root):
            return True

    return False


def ensure_not_cancelled(cancel_callback=None):
    if cancel_callback and cancel_callback():
        raise BackupCancelledError("Backup cancelado pelo usuario.")


def add_directory_to_zip(archive, directory, config=None, backup_destination=None):
    normalized_directory = normalize_path(directory)

    if not os.path.isdir(normalized_directory):
        return

    if is_path_ignored(normalized_directory, config, backup_destination):
        return

    base_name = os.path.basename(normalized_directory.rstrip("\\/")) or "diretorio"

    for root, dirs, files in os.walk(normalized_directory):
        dirs[:] = [
            current_dir
            for current_dir in dirs
            if not is_path_ignored(os.path.join(root, current_dir), config, backup_destination)
        ]

        for file_name in files:
            file_path = os.path.join(root, file_name)

            if is_path_ignored(file_path, config, backup_destination):
                continue

            relative_path = os.path.relpath(file_path, normalized_directory)
            archive_name = os.path.join(base_name, relative_path)
            archive.write(file_path, arcname=archive_name)


def build_backup_manifest(directories=None, config=None, backup_destination=None):
    directories = directories or get_monitored_directories(config)
    manifest = []

    for directory in directories:
        normalized_directory = normalize_path(directory)

        if not os.path.isdir(normalized_directory):
            continue

        if is_path_ignored(normalized_directory, config, backup_destination):
            continue

        base_name = os.path.basename(normalized_directory.rstrip("\\/")) or "diretorio"

        for root, dirs, files in os.walk(normalized_directory):
            dirs[:] = [
                current_dir
                for current_dir in dirs
                if not is_path_ignored(os.path.join(root, current_dir), config, backup_destination)
            ]

            for file_name in files:
                file_path = os.path.join(root, file_name)

                if is_path_ignored(file_path, config, backup_destination):
                    continue

                relative_path = os.path.relpath(file_path, normalized_directory)
                archive_name = os.path.join(base_name, relative_path)
                manifest.append((file_path, archive_name))

    return manifest


def count_files_in_directories(directories=None, config=None, backup_destination=None):
    manifest = build_backup_manifest(directories, config, backup_destination)
    return len(manifest)


def deduplicate_manifest(manifest):
    unique_entries = []
    warnings = []
    seen_hashes = {}
    skipped_duplicates = []

    for source_path, archive_name in manifest:
        try:
            file_hash = calculate_file_hash(source_path)
        except OSError as error:
            warnings.append(
                {
                    "path": source_path,
                    "error": f"Falha ao calcular hash para deduplicacao: {error}"
                }
            )
            unique_entries.append((source_path, archive_name))
            continue

        existing_path = seen_hashes.get(file_hash)

        if existing_path:
            skipped_duplicates.append(
                {
                    "path": source_path,
                    "kept_path": existing_path,
                    "reason": "Arquivo duplicado ignorado por hash."
                }
            )
            continue

        seen_hashes[file_hash] = source_path
        unique_entries.append((source_path, archive_name))

    return unique_entries, skipped_duplicates, warnings


def build_file_snapshot(manifest):
    snapshot = {}

    for source_path, archive_name in manifest:
        try:
            stat = os.stat(source_path)
            file_hash = calculate_file_hash(source_path)
        except OSError:
            continue

        snapshot[archive_name] = {
            "name": os.path.basename(source_path),
            "source_path": source_path,
            "archive_name": archive_name,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "file_hash": file_hash,
        }

    return snapshot


def normalize_priority(priority):
    normalized = str(priority or "").strip().lower()

    if normalized in {PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH}:
        return normalized

    return PRIORITY_LOW


def load_priority_state():
    return load_json(PRIORITY_STATE_PATH, {})


def save_priority_state(state):
    save_json(PRIORITY_STATE_PATH, state)


def parse_iso_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_dataset_priority_index():
    index = {
        "by_source_path": {},
        "by_archive_name": {},
    }

    if not os.path.exists(DATASET_PATH):
        return index

    with open(DATASET_PATH, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            source_path = row.get("source_path")
            archive_name = row.get("archive_name")

            if source_path:
                index["by_source_path"][normalize_path(source_path)] = row

            if archive_name:
                index["by_archive_name"][normalize_archive_name(archive_name)] = row

    return index


def find_priority_metadata(source_path, archive_name, priority_index=None):
    priority_index = priority_index or load_dataset_priority_index()
    normalized_source = normalize_path(source_path)
    normalized_archive = normalize_archive_name(archive_name)

    return (
        priority_index["by_source_path"].get(normalized_source)
        or priority_index["by_archive_name"].get(normalized_archive)
        or {}
    )


def get_priority_file_hash(source_path, metadata):
    file_hash = metadata.get("file_hash")

    if file_hash:
        return file_hash

    try:
        return calculate_file_hash(source_path)
    except OSError:
        return ""


def should_include_priority_file(source_path, archive_name, metadata, state_entry, now):
    priority = normalize_priority(metadata.get("priority"))
    last_backup_at = parse_iso_datetime(state_entry.get("last_backup_at"))
    current_hash = get_priority_file_hash(source_path, metadata)
    previous_hash = state_entry.get("last_backup_hash", "")
    hash_changed = not previous_hash or current_hash != previous_hash
    interval = get_backup_interval(priority)
    dev_mode = is_dev_mode_enabled()

    if not last_backup_at:
        return True, "primeiro backup pela politica de prioridade"

    if priority == PRIORITY_HIGH and not dev_mode:
        today = now.date().isoformat()

        if state_entry.get("last_daily_backup_date") != today:
            return True, "primeiro backup de alta prioridade no dia"

        if now - last_backup_at >= interval and hash_changed:
            return True, "arquivo de alta prioridade alterado no intervalo de 4 horas"

        return False, "alta prioridade ainda dentro do intervalo"

    if now - last_backup_at >= interval:
        if dev_mode:
            return True, "arquivo elegivel em intervalo reduzido de DEV MODE"
        return True, f"intervalo vencido para prioridade {priority}"

    return False, f"prioridade {priority} ainda dentro do intervalo"


def build_priority_eligible_manifest(
    directories=None,
    config=None,
    backup_destination=None,
    now=None,
    priority_index=None,
    index=None
):
    now = now or datetime.now()
    config = config or load_config()
    backup_destination = backup_destination or get_backup_destination(config)
    log_dev_mode_intervals()
    full_manifest = build_backup_manifest(
        directories=directories,
        config=config,
        backup_destination=backup_destination
    )
    priority_index = priority_index or load_dataset_priority_index()
    index = index or load_incremental_index(backup_destination)
    due_manifest = []
    decisions = []

    for source_path, archive_name in full_manifest:
        metadata = find_priority_metadata(source_path, archive_name, priority_index)
        priority = normalize_priority(metadata.get("priority"))
        state_key = normalize_path(source_path)
        index_entry = index.get("files", {}).get(state_key, {})
        last_backup_at = parse_iso_datetime(index_entry.get("last_backup_at"))
        include_file = False
        reason = ""

        if priority == PRIORITY_LOW:
            reason = "baixa prioridade aguardando backup completo"
        else:
            time_eligible = is_file_eligible_for_backup(metadata, index_entry, now)

            if time_eligible:
                changed, current_hash, change_reason = has_priority_file_changed(
                    source_path,
                    index_entry,
                    metadata
                )
                include_file = changed
                reason = change_reason

                if (
                    include_file
                    and is_dev_mode_enabled()
                    and last_backup_at
                    and current_hash
                ):
                    log_backup_decision(
                        "DEV MODE",
                        f"Arquivo elegivel e alterado em intervalo reduzido: {os.path.basename(source_path)}"
                    )
            else:
                reason = f"prioridade {priority} ainda dentro do intervalo"
                log_dev_mode_not_eligible(source_path, priority, last_backup_at, now)

        if include_file:
            log_backup_decision(
                "INFO",
                f"Arquivo incluido na snapshot por prioridade: {source_path}"
            )

        decisions.append(
            {
                "source_path": source_path,
                "archive_name": archive_name,
                "priority": priority,
                "included": include_file,
                "reason": reason,
                "last_backup_at": index_entry.get("last_backup_at", ""),
                "last_hash": index_entry.get("last_hash", ""),
                "required_interval": format_interval_for_log(get_backup_interval(priority)),
            }
        )

        if include_file:
            due_manifest.append((source_path, archive_name))

    return due_manifest, decisions, priority_index


def build_priority_backup_manifest(
    directories=None,
    config=None,
    backup_destination=None,
    now=None
):
    return build_priority_eligible_manifest(
        directories=directories,
        config=config,
        backup_destination=backup_destination,
        now=now,
    )


def determine_priority_scope(manifest, priority_index=None):
    priority_index = priority_index or load_dataset_priority_index()
    priorities = {
        normalize_priority(
            find_priority_metadata(source_path, archive_name, priority_index).get("priority")
        )
        for source_path, archive_name in manifest
    }
    priorities.discard(PRIORITY_LOW)

    if len(priorities) == 1:
        return next(iter(priorities))

    if priorities:
        return "mixed"

    return PRIORITY_LOW


def update_priority_state_after_backup(manifest, current_snapshot, now=None, priority_index=None):
    if not manifest:
        return

    now = now or datetime.now()
    priority_index = priority_index or load_dataset_priority_index()
    state = load_priority_state()

    for source_path, archive_name in manifest:
        metadata = find_priority_metadata(source_path, archive_name, priority_index)
        priority = normalize_priority(metadata.get("priority"))
        snapshot_entry = current_snapshot.get(archive_name, {})
        state_key = normalize_path(source_path)
        previous_entry = state.get(state_key, {})
        next_entry = {
            "source_path": source_path,
            "archive_name": archive_name,
            "priority": priority,
            "last_backup_at": now.isoformat(timespec="seconds"),
            "last_backup_hash": snapshot_entry.get("file_hash", ""),
        }

        if priority == PRIORITY_HIGH:
            next_entry["last_daily_backup_date"] = now.date().isoformat()
        elif previous_entry.get("last_daily_backup_date"):
            next_entry["last_daily_backup_date"] = previous_entry.get("last_daily_backup_date")

        state[state_key] = next_entry

    save_priority_state(state)


def history_entry_matches_scope(entry, username=None, company_id=None):
    if not isinstance(entry, dict):
        return False

    if username is not None and entry.get("user", "sistema") != username:
        return False

    if company_id is not None and entry.get("company_id", "default") != company_id:
        return False

    return True


def get_latest_history_snapshot(include_partial=False, username=None, company_id=None):
    history = load_history()

    for entry in reversed(history):
        if not history_entry_matches_scope(entry, username, company_id):
            continue

        if entry.get("partial_backup") and not include_partial:
            continue

        snapshot = entry.get("file_snapshot")

        if isinstance(snapshot, dict):
            return snapshot

    return {}


def is_full_history_entry(entry):
    if not isinstance(entry, dict):
        return False

    if entry.get("partial_backup") or entry.get("priority_policy"):
        return False

    return bool(entry.get("file_snapshot"))


def get_latest_full_history_entry(username=None, company_id=None):
    history = load_history()

    for entry in reversed(history):
        if not history_entry_matches_scope(entry, username, company_id):
            continue

        if is_full_history_entry(entry):
            return entry

    return None


def build_file_changes(previous_snapshot, current_snapshot, detect_deletions=True):
    changes = []
    previous_keys = set(previous_snapshot.keys())
    current_keys = set(current_snapshot.keys())

    for archive_name in sorted(current_keys - previous_keys):
        file_data = current_snapshot[archive_name]
        changes.append(
            {
                "action": "adicionado",
                "name": file_data.get("name", ""),
                "archive_name": archive_name,
                "source_path": file_data.get("source_path", ""),
                "size_bytes": file_data.get("size_bytes", 0),
                "modified_at": file_data.get("modified_at", ""),
                "priority": file_data.get("priority", ""),
                "file_hash": file_data.get("file_hash", ""),
                "object_path": file_data.get("object_path", ""),
                "snapshot_path": file_data.get("snapshot_path", ""),
                "storage_mode": file_data.get("storage_mode", ""),
            }
        )

    for archive_name in sorted(previous_keys & current_keys):
        previous_file = previous_snapshot[archive_name]
        current_file = current_snapshot[archive_name]

        if previous_file.get("file_hash") == current_file.get("file_hash"):
            continue

        changes.append(
            {
                "action": "alterado",
                "name": current_file.get("name", ""),
                "archive_name": archive_name,
                "source_path": current_file.get("source_path", ""),
                "size_bytes": current_file.get("size_bytes", 0),
                "modified_at": current_file.get("modified_at", ""),
                "priority": current_file.get("priority", ""),
                "file_hash": current_file.get("file_hash", ""),
                "object_path": current_file.get("object_path", ""),
                "snapshot_path": current_file.get("snapshot_path", ""),
                "storage_mode": current_file.get("storage_mode", ""),
            }
        )

    if detect_deletions:
        for archive_name in sorted(previous_keys - current_keys):
            file_data = previous_snapshot[archive_name]
            changes.append(
                {
                    "action": "excluido",
                    "name": file_data.get("name", ""),
                    "archive_name": archive_name,
                    "source_path": file_data.get("source_path", ""),
                    "size_bytes": file_data.get("size_bytes", 0),
                    "modified_at": file_data.get("modified_at", ""),
                    "priority": file_data.get("priority", ""),
                    "file_hash": file_data.get("file_hash", ""),
                    "object_path": file_data.get("object_path", ""),
                    "snapshot_path": file_data.get("snapshot_path", ""),
                    "storage_mode": file_data.get("storage_mode", ""),
                }
            )

    return changes


def sanitize_backup_name(name):
    if not name:
        return ""

    sanitized = re.sub(r"[^A-Za-z0-9._ -]+", "", name.strip())
    sanitized = re.sub(r"\s+", "_", sanitized)
    sanitized = sanitized.strip("._- ")
    return sanitized[:60]


def log_backup_decision(level, message):
    print(f"[{level}] {message}")


def is_dev_mode_enabled():
    load_backup_env_file()
    value = os.getenv("BACKUP_DEV_MODE", "false").strip().lower()
    return value == "true"


def get_backup_intervals():
    if is_dev_mode_enabled():
        return DEV_PRIORITY_INTERVALS.copy()

    return PRIORITY_INTERVALS.copy()


def get_backup_interval(priority):
    normalized_priority = normalize_priority(priority)
    return get_backup_intervals().get(normalized_priority)


def get_priority_scheduler_check_interval_seconds():
    return 60 if is_dev_mode_enabled() else 600


def format_interval_for_log(interval):
    if interval is None:
        return "desconhecido"

    total_seconds = int(interval.total_seconds())

    if total_seconds % 86400 == 0:
        days = total_seconds // 86400
        return f"{days}d"

    if total_seconds % 3600 == 0:
        hours = total_seconds // 3600
        return f"{hours}h"

    if total_seconds % 60 == 0:
        minutes = total_seconds // 60
        return f"{minutes}min"

    return f"{total_seconds}s"


def log_dev_mode_intervals():
    if not is_dev_mode_enabled():
        return

    intervals = get_backup_intervals()
    log_backup_decision("DEV MODE", "Intervalos reduzidos ativos")
    log_backup_decision(
        "DEV MODE",
        (
            f"baixa={format_interval_for_log(intervals.get(PRIORITY_LOW))} "
            f"media={format_interval_for_log(intervals.get(PRIORITY_MEDIUM))} "
            f"alta={format_interval_for_log(intervals.get(PRIORITY_HIGH))}"
        )
    )


def log_dev_mode_not_eligible(source_path, priority, last_backup_at, now):
    if not is_dev_mode_enabled() or not last_backup_at:
        return

    interval = get_backup_interval(priority)
    elapsed = now - last_backup_at
    log_backup_decision(
        "DEV MODE",
        (
            f"Arquivo ainda nao elegivel: {os.path.basename(source_path)} | "
            f"prioridade={priority} | "
            f"ultimo_backup={last_backup_at.isoformat(timespec='seconds')} | "
            f"decorrido={format_interval_for_log(elapsed)} | "
            f"necessario={format_interval_for_log(interval)}"
        )
    )


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_incremental_storage_paths(backup_destination=None, now=None):
    destination = resolve_configured_path(backup_destination or get_backup_destination())
    now = now or datetime.now()
    day_folder = now.strftime("%Y-%m-%d")
    day_root = os.path.join(destination, day_folder)

    return {
        "root": destination,
        "day_root": day_root,
        "objects": os.path.join(day_root, OBJECTS_DIRNAME),
        "snapshots": os.path.join(day_root, SNAPSHOTS_DIRNAME),
        "index": os.path.join(destination, INDEX_FILENAME),
    }


def ensure_incremental_storage(backup_destination=None, now=None):
    paths = get_incremental_storage_paths(backup_destination, now=now)
    os.makedirs(paths["objects"], exist_ok=True)
    os.makedirs(paths["snapshots"], exist_ok=True)
    return paths


def build_default_incremental_index():
    return {
        "version": INDEX_VERSION,
        "files": {},
        "objects": {},
    }


def normalize_incremental_index(index):
    if not isinstance(index, dict):
        index = build_default_incremental_index()

    if not isinstance(index.get("files"), dict):
        index["files"] = {}

    if not isinstance(index.get("objects"), dict):
        index["objects"] = {}

    index["version"] = parse_int(index.get("version"), INDEX_VERSION) or INDEX_VERSION
    return index


def load_incremental_index(backup_destination=None):
    paths = get_incremental_storage_paths(backup_destination)
    return normalize_incremental_index(
        load_json(paths["index"], build_default_incremental_index())
    )


def save_incremental_index(backup_destination, index):
    paths = get_incremental_storage_paths(backup_destination)
    save_json_atomic(paths["index"], normalize_incremental_index(index))


def is_first_incremental_backup(backup_destination):
    index = load_incremental_index(backup_destination)
    return not index.get("files") and not index.get("objects")


def start_background_classification_scan():
    def worker():
        try:
            from scanner.scanner import run_scanner

            run_scanner()
        except Exception as error:
            log_backup_decision(
                "ERROR",
                f"Falha na classificacao em segundo plano: {error}"
            )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def build_object_relative_path(file_hash, now=None):
    now = now or datetime.now()
    day_folder = now.strftime("%Y-%m-%d")
    return f"{day_folder}/{OBJECTS_DIRNAME}/{file_hash}"


def resolve_storage_relative_path(storage_root, relative_path):
    normalized_relative = str(relative_path or "").replace("\\", "/").strip("/")
    return os.path.join(storage_root, *normalized_relative.split("/"))


def build_unique_snapshot_path(snapshots_directory, now):
    base_snapshot_id = f"snapshot_{now.strftime('%Y-%m-%d_%H-%M-%S')}"
    snapshot_id = base_snapshot_id
    counter = 2

    while True:
        snapshot_path = os.path.join(snapshots_directory, f"{snapshot_id}.json")

        if not os.path.exists(snapshot_path):
            return snapshot_id, snapshot_path

        snapshot_id = f"{base_snapshot_id}_{counter}"
        counter += 1


def get_metadata_priority_score(metadata):
    if not isinstance(metadata, dict):
        return ""

    return metadata.get("priority_score", metadata.get("score", ""))


def format_stat_modified_at(stat_result):
    return datetime.fromtimestamp(stat_result.st_mtime).isoformat(timespec="seconds")


def build_incremental_snapshot_entry(
    source_path,
    archive_name,
    file_hash,
    object_path,
    priority,
    score,
    size,
    modified_at,
    status,
    error="",
    encryption=None
):
    entry = {
        "original_path": source_path,
        "source_path": source_path,
        "archive_name": normalize_archive_name(archive_name),
        "file_name": os.path.basename(source_path),
        "hash": file_hash,
        "file_hash": file_hash,
        "object_path": object_path,
        "priority": priority,
        "score": score,
        "size": size,
        "size_bytes": size,
        "modified_at": modified_at,
        "status": status,
        "error": error,
    }

    if encryption:
        entry["encryption"] = encryption

    return entry


def build_history_snapshot_from_incremental_files(files, snapshot_path):
    snapshot = {}

    for file_data in files:
        archive_name = normalize_archive_name(file_data.get("archive_name", ""))
        file_hash = file_data.get("hash") or file_data.get("file_hash")

        if not archive_name or not file_hash:
            continue

        if file_data.get("status") == "error":
            continue

        snapshot[archive_name] = {
            "name": file_data.get("file_name", ""),
            "source_path": file_data.get("original_path", ""),
            "archive_name": archive_name,
            "size_bytes": file_data.get("size", 0),
            "modified_at": file_data.get("modified_at", ""),
            "file_hash": file_hash,
            "object_path": file_data.get("object_path", ""),
            "snapshot_path": snapshot_path,
            "storage_mode": "incremental",
        }

        if file_data.get("encryption"):
            snapshot[archive_name]["encryption"] = file_data.get("encryption")

    return snapshot


def increment_status_count(counts, status):
    counts[status] = counts.get(status, 0) + 1


def update_object_index_entry(
    index,
    file_hash,
    object_path,
    source_path,
    size,
    now,
    encryption=None
):
    objects = index.setdefault("objects", {})
    object_entry = objects.get(file_hash, {})
    original_names = object_entry.get("original_names", [])

    if not isinstance(original_names, list):
        original_names = []

    file_name = os.path.basename(source_path)

    if file_name and file_name not in original_names:
        original_names.append(file_name)

    object_entry.update(
        {
            "object_path": object_path,
            "original_names": original_names,
            "size": size,
            "created_at": object_entry.get("created_at")
            or now.isoformat(timespec="seconds"),
            "reference_count": parse_int(object_entry.get("reference_count")),
        }
    )

    if encryption:
        object_entry["encryption"] = encryption

    objects[file_hash] = object_entry


def update_file_index_entry(
    index,
    source_path,
    archive_name,
    file_hash,
    object_path,
    priority,
    stat_result,
    now,
    encryption=None
):
    files = index.setdefault("files", {})
    state_key = normalize_path(source_path)
    previous_entry = files.get(state_key, {})
    backup_count = parse_int(previous_entry.get("backup_count")) + 1
    next_entry = {
        "source_path": source_path,
        "archive_name": normalize_archive_name(archive_name),
        "last_hash": file_hash,
        "last_priority": priority,
        "last_backup_at": now.isoformat(timespec="seconds"),
        "last_modified_at": format_stat_modified_at(stat_result),
        "object_path": object_path,
        "size": stat_result.st_size,
        "backup_count": backup_count,
    }

    if encryption:
        next_entry["encryption"] = encryption

    if priority == PRIORITY_HIGH:
        next_entry["last_daily_backup_date"] = now.date().isoformat()

    files[state_key] = next_entry
    return next_entry


def refresh_object_reference_counts(index):
    references = {}

    for file_entry in index.get("files", {}).values():
        file_hash = file_entry.get("last_hash")

        if file_hash:
            references[file_hash] = references.get(file_hash, 0) + 1

    for file_hash, object_entry in index.get("objects", {}).items():
        object_entry["reference_count"] = references.get(file_hash, 0)


def is_file_eligible_for_backup(file_metadata, index_entry, now):
    file_metadata = file_metadata or {}
    index_entry = index_entry or {}
    priority = normalize_priority(
        file_metadata.get("priority") or index_entry.get("last_priority")
    )
    last_backup_at = parse_iso_datetime(index_entry.get("last_backup_at"))
    interval = get_backup_interval(priority)
    dev_mode = is_dev_mode_enabled()

    if not last_backup_at:
        return True

    if priority == PRIORITY_HIGH and not dev_mode:
        today = now.date().isoformat()

        if index_entry.get("last_daily_backup_date") != today:
            return True

        return now - last_backup_at >= interval

    return now - last_backup_at >= interval


def has_priority_file_changed(source_path, index_entry, metadata):
    previous_hash = index_entry.get("last_hash") or index_entry.get("last_backup_hash", "")

    if not previous_hash:
        return True, "", "arquivo novo sem hash anterior"

    current_hash = get_priority_file_hash(source_path, metadata)

    if not current_hash:
        return True, "", "hash atual indisponivel; arquivo sera avaliado pelo backup"

    if current_hash != previous_hash:
        return True, current_hash, "arquivo alterado desde a ultima snapshot"

    return False, current_hash, "arquivo sem alteracao desde a ultima snapshot"


def normalize_master_key(master_key):
    if not master_key:
        return None

    if isinstance(master_key, bytes):
        return master_key

    try:
        return crypto_service.b64decode(master_key)
    except (ValueError, TypeError):
        return None


def build_backup_encryption_context(encryption_context):
    if not isinstance(encryption_context, dict):
        return None

    master_key = normalize_master_key(encryption_context.get("master_key"))

    if not master_key:
        return None

    backup_key = crypto_service.generate_key()
    wrapped_key = crypto_service.encrypt_key(
        master_key,
        backup_key,
        b"incremental-backup-key",
    )
    return {
        "enabled": True,
        "algorithm": crypto_service.ENCRYPTION_ALGORITHM,
        "master_key": master_key,
        "backup_key": backup_key,
        "encrypted_backup_key": wrapped_key["encrypted_key"],
        "backup_key_nonce": wrapped_key["key_nonce"],
        "user_id": encryption_context.get("user_id", ""),
        "company_id": encryption_context.get("company_id", "default"),
    }


def build_object_encryption_metadata(backup_encryption, file_nonce):
    if not backup_encryption:
        return None

    return {
        "encrypted": True,
        "algorithm": backup_encryption["algorithm"],
        "encrypted_backup_key": backup_encryption["encrypted_backup_key"],
        "backup_key_nonce": backup_encryption["backup_key_nonce"],
        "file_nonce": file_nonce,
        "auth_tag": "included_in_ciphertext",
        "user_id": backup_encryption.get("user_id", ""),
        "company_id": backup_encryption.get("company_id", "default"),
    }


def get_object_encryption_metadata(index, file_hash):
    object_entry = index.get("objects", {}).get(file_hash, {})
    metadata = object_entry.get("encryption")
    return metadata if isinstance(metadata, dict) else None


def decrypt_storage_object_to_path(object_abs_path, target_path, encryption_metadata, user_master_key):
    if not encryption_metadata:
        with open(object_abs_path, "rb") as source_file:
            compressed_data = source_file.read()
        raw_data = decompress_bytes(compressed_data)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "wb") as target_file:
            target_file.write(raw_data)
        return

    master_key = normalize_master_key(user_master_key)

    if not master_key:
        raise ValueError("Chave de sessao ausente para restaurar backup criptografado.")

    backup_key = crypto_service.decrypt_key(
        master_key,
        encryption_metadata["encrypted_backup_key"],
        encryption_metadata["backup_key_nonce"],
        b"incremental-backup-key",
    )

    with open(object_abs_path, "rb") as source_file:
        ciphertext = source_file.read()

    compressed_data = crypto_service.decrypt_bytes(
        backup_key,
        crypto_service.b64decode(encryption_metadata["file_nonce"]),
        ciphertext,
        b"incremental-object",
    )

    raw_data = decompress_bytes(compressed_data)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "wb") as target_file:
        target_file.write(raw_data)


def read_storage_object_bytes(object_abs_path, encryption_metadata, user_master_key):
    if not encryption_metadata:
        with open(object_abs_path, "rb") as source_file:
            compressed_data = source_file.read()
        return decompress_bytes(compressed_data)

    master_key = normalize_master_key(user_master_key)

    if not master_key:
        raise ValueError("Chave de sessao ausente para exportar backup criptografado.")

    backup_key = crypto_service.decrypt_key(
        master_key,
        encryption_metadata["encrypted_backup_key"],
        encryption_metadata["backup_key_nonce"],
        b"incremental-backup-key",
    )

    with open(object_abs_path, "rb") as source_file:
        ciphertext = source_file.read()

    compressed_data = crypto_service.decrypt_bytes(
        backup_key,
        crypto_service.b64decode(encryption_metadata["file_nonce"]),
        ciphertext,
        b"incremental-object",
    )

    return decompress_bytes(compressed_data)


def _get_zstd_compressor():
    """Retorna (e cacheia) um compressor zstd com o nível configurado."""
    compressor = getattr(_ZSTD_THREAD_LOCAL, "compressor", None)

    if compressor is None:
        compressor = zstd.ZstdCompressor(level=OBJECT_COMPRESSION_LEVEL)
        _ZSTD_THREAD_LOCAL.compressor = compressor

    return compressor


def _get_zstd_decompressor():
    """Retorna (e cacheia) um decompressor zstd."""
    if not hasattr(_get_zstd_decompressor, "_cached"):
        _get_zstd_decompressor._cached = zstd.ZstdDecompressor()
    return _get_zstd_decompressor._cached


def read_and_compress_file(source_path):
    """Lê o arquivo e retorna os bytes comprimidos com zstandard (zstd)."""
    with open(source_path, "rb") as source_file:
        raw_data = source_file.read()
    return _get_zstd_compressor().compress(raw_data)


def decompress_bytes(data):
    """Descomprime dados que foram comprimidos com zstandard (zstd)."""
    return _get_zstd_decompressor().decompress(data)


def store_incremental_object(source_path, object_path, backup_encryption=None):
    temporary_path = f"{object_path}.{os.getpid()}.tmp"

    try:
        # Comprimir o arquivo em memória antes de armazenar
        compressed_data = read_and_compress_file(source_path)
        encryption_metadata = None

        if backup_encryption:
            # Criptografar o dado já comprimido
            encrypted = crypto_service.encrypt_bytes_raw_data(
                compressed_data,
                backup_encryption["backup_key"],
                b"incremental-object",
            )
            encryption_metadata = build_object_encryption_metadata(
                backup_encryption,
                encrypted["file_nonce"],
            )
            with open(temporary_path, "wb") as target_file:
                target_file.write(encrypted["ciphertext"])
        else:
            # Salvar o dado comprimido diretamente
            with open(temporary_path, "wb") as target_file:
                target_file.write(compressed_data)

        os.replace(temporary_path, object_path)
        return encryption_metadata
    except OSError:
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        raise


def get_incremental_object_worker_count(total_objects):
    if total_objects <= 1:
        return 1

    available_cpus = os.cpu_count() or 2
    return min(4, total_objects, max(2, available_cpus))


def build_not_eligible_snapshot_entry(
    source_path,
    archive_name,
    metadata,
    index_entry
):
    file_hash = index_entry.get("last_hash", "")
    object_path = index_entry.get("object_path", "")
    priority = normalize_priority(
        metadata.get("priority") or index_entry.get("last_priority")
    )
    score = get_metadata_priority_score(metadata)

    return build_incremental_snapshot_entry(
        source_path=source_path,
        archive_name=archive_name,
        file_hash=file_hash,
        object_path=object_path,
        priority=priority,
        score=score,
        size=parse_int(index_entry.get("size")),
        modified_at=index_entry.get("last_modified_at", ""),
        status="skipped_not_eligible",
        encryption=index_entry.get("encryption"),
    )


def run_incremental_backup(
    directories=None,
    backup_destination=None,
    config=None,
    now=None,
    manifest=None,
    priority_policy=False,
    priority_index=None,
    trigger="manual",
    progress_callback=None,
    cancel_callback=None,
    encryption_context=None
):
    config = config or load_config()
    directories = directories or get_monitored_directories(config)
    backup_destination = resolve_configured_path(
        backup_destination or get_backup_destination(config)
    )
    now = now or datetime.now()

    if not directories and manifest is None:
        raise ValueError("Adicione ao menos um diretorio antes de iniciar o backup.")

    storage_paths = ensure_incremental_storage(backup_destination, now=now)
    index = load_incremental_index(backup_destination)
    backup_encryption = build_backup_encryption_context(encryption_context)
    priority_index = priority_index or load_dataset_priority_index()
    manifest = manifest if manifest is not None else build_backup_manifest(
        directories=directories,
        config=config,
        backup_destination=backup_destination
    )
    snapshot_id, snapshot_path = build_unique_snapshot_path(
        storage_paths["snapshots"],
        now
    )
    files = []
    warnings = []
    skipped_duplicates = []
    status_counts = {}
    total_entries = len(manifest)

    if progress_callback:
        progress_callback(0, total_entries, "Preparando backup incremental...")

    if priority_policy:
        log_dev_mode_intervals()

    result_entries = [None] * total_entries
    pending_store_items = {}
    pending_store_jobs = {}
    completed_entries = 0

    def record_progress(archive_name):
        nonlocal completed_entries
        completed_entries += 1

        if progress_callback:
            progress_callback(completed_entries, total_entries, archive_name)

    def record_entry(item_index, archive_name, entry):
        result_entries[item_index - 1] = entry
        increment_status_count(status_counts, entry["status"])
        record_progress(archive_name)

    def record_success_item(item, encryption_metadata):
        update_object_index_entry(
            index,
            item["file_hash"],
            item["object_path"],
            item["source_path"],
            item["stat_result"].st_size,
            now,
            encryption=encryption_metadata,
        )
        update_file_index_entry(
            index,
            item["source_path"],
            item["archive_name"],
            item["file_hash"],
            item["object_path"],
            item["priority"],
            item["stat_result"],
            now,
            encryption=encryption_metadata,
        )
        entry = build_incremental_snapshot_entry(
            source_path=item["source_path"],
            archive_name=item["archive_name"],
            file_hash=item["file_hash"],
            object_path=item["object_path"],
            priority=item["priority"],
            score=item["score"],
            size=item["stat_result"].st_size,
            modified_at=format_stat_modified_at(item["stat_result"]),
            status=item["status"],
            encryption=encryption_metadata,
        )
        record_entry(item["item_index"], item["archive_name"], entry)

    def record_store_error(item, error):
        entry = build_incremental_snapshot_entry(
            source_path=item["source_path"],
            archive_name=item["archive_name"],
            file_hash=item["file_hash"],
            object_path=item["object_path"],
            priority=item["priority"],
            score=item["score"],
            size=item["stat_result"].st_size,
            modified_at=format_stat_modified_at(item["stat_result"]),
            status="error",
            error=str(error)
        )
        warnings.append({"path": item["source_path"], "error": str(error)})
        log_backup_decision(
            "ERROR",
            f"Falha ao armazenar objeto: {item['source_path']} ({error})"
        )
        record_entry(item["item_index"], item["archive_name"], entry)

    for item_index, (source_path, archive_name) in enumerate(manifest, start=1):
        ensure_not_cancelled(cancel_callback)
        metadata = find_priority_metadata(source_path, archive_name, priority_index)
        priority = normalize_priority(metadata.get("priority"))
        score = get_metadata_priority_score(metadata)
        state_key = normalize_path(source_path)
        index_entry = index.get("files", {}).get(state_key, {})

        if priority_policy and not is_file_eligible_for_backup(metadata, index_entry, now):
            entry = build_not_eligible_snapshot_entry(
                source_path,
                archive_name,
                metadata,
                index_entry
            )
            log_backup_decision(
                "INFO",
                f"Arquivo ignorado, ainda nao elegivel pela politica: {source_path}"
            )
            record_entry(item_index, archive_name, entry)

            continue

        if priority_policy and is_dev_mode_enabled() and index_entry.get("last_backup_at"):
            log_backup_decision(
                "DEV MODE",
                f"Arquivo elegivel em intervalo reduzido: {os.path.basename(source_path)}"
            )

        try:
            stat_result = os.stat(source_path)
            file_hash = calculate_file_hash(source_path)
        except OSError as error:
            entry = build_incremental_snapshot_entry(
                source_path=source_path,
                archive_name=archive_name,
                file_hash="",
                object_path="",
                priority=priority,
                score=score,
                size=0,
                modified_at="",
                status="error",
                error=str(error)
            )
            warnings.append({"path": source_path, "error": str(error)})
            log_backup_decision(
                "ERROR",
                f"Falha ao calcular hash: {source_path} ({error})"
            )
            record_entry(item_index, archive_name, entry)

            continue

        existing_object = index.get("objects", {}).get(file_hash, {})
        object_path = existing_object.get("object_path") or build_object_relative_path(
            file_hash,
            now=now
        )
        object_abs_path = resolve_storage_relative_path(
            storage_paths["root"],
            object_path
        )
        previous_hash = index_entry.get("last_hash")
        encryption_metadata = get_object_encryption_metadata(index, file_hash)

        if previous_hash == file_hash and os.path.exists(object_abs_path):
            status = "skipped_unchanged"
            log_backup_decision(
                "INFO",
                f"Arquivo sem alteracao, mantendo referencia: {source_path}"
            )
            record_success_item(
                {
                    "item_index": item_index,
                    "source_path": source_path,
                    "archive_name": archive_name,
                    "file_hash": file_hash,
                    "object_path": object_path,
                    "priority": priority,
                    "score": score,
                    "stat_result": stat_result,
                    "status": status,
                },
                encryption_metadata,
            )
        elif os.path.exists(object_abs_path):
            status = "referenced_existing_object"
            skipped_duplicates.append(
                {
                    "path": source_path,
                    "hash": file_hash,
                    "reason": "Hash ja existente no armazenamento incremental."
                }
            )
            log_backup_decision(
                "INFO",
                f"Hash ja existente, criando apenas referencia: {source_path}"
            )
            record_success_item(
                {
                    "item_index": item_index,
                    "source_path": source_path,
                    "archive_name": archive_name,
                    "file_hash": file_hash,
                    "object_path": object_path,
                    "priority": priority,
                    "score": score,
                    "stat_result": stat_result,
                    "status": status,
                },
                encryption_metadata,
            )
        else:
            status = "stored_new_object"

            if file_hash in pending_store_jobs:
                status = "referenced_existing_object"
                skipped_duplicates.append(
                    {
                        "path": source_path,
                        "hash": file_hash,
                        "reason": "Hash ja existente no armazenamento incremental."
                    }
                )
                log_backup_decision(
                    "INFO",
                    f"Hash ja pendente, criando apenas referencia: {source_path}"
                )
            else:
                pending_store_jobs[file_hash] = {
                    "source_path": source_path,
                    "object_abs_path": object_abs_path,
                }

            pending_store_items.setdefault(file_hash, []).append(
                {
                    "item_index": item_index,
                    "source_path": source_path,
                    "archive_name": archive_name,
                    "file_hash": file_hash,
                    "object_path": object_path,
                    "priority": priority,
                    "score": score,
                    "stat_result": stat_result,
                    "status": status,
                }
            )

    ensure_not_cancelled(cancel_callback)

    if pending_store_jobs:
        worker_count = get_incremental_object_worker_count(len(pending_store_jobs))

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_hash = {
                executor.submit(
                    store_incremental_object,
                    job["source_path"],
                    job["object_abs_path"],
                    backup_encryption=backup_encryption,
                ): file_hash
                for file_hash, job in pending_store_jobs.items()
            }

            for future in as_completed(future_to_hash):
                ensure_not_cancelled(cancel_callback)
                file_hash = future_to_hash[future]
                items = pending_store_items.get(file_hash, [])

                try:
                    encryption_metadata = future.result()
                    for item in items:
                        if item["status"] == "stored_new_object":
                            log_backup_decision(
                                "INFO",
                                f"Novo objeto armazenado: {item['source_path']}"
                            )
                        record_success_item(item, encryption_metadata)
                except OSError as error:
                    for item in items:
                        record_store_error(item, error)

    files = [
        entry
        for entry in result_entries
        if entry is not None
    ]

    refresh_object_reference_counts(index)
    snapshot = {
        "snapshot_id": snapshot_id,
        "created_at": now.isoformat(timespec="seconds"),
        "trigger": trigger,
        "storage_root": storage_paths["root"],
        "index_path": storage_paths["index"],
        "total_files": len(files),
        "status_counts": status_counts,
        "files": files,
    }

    if backup_encryption:
        snapshot["encryption"] = {
            "enabled": True,
            "algorithm": backup_encryption["algorithm"],
            "key_scope": "incremental_objects",
            "user_id": backup_encryption.get("user_id", ""),
            "company_id": backup_encryption.get("company_id", "default"),
        }

    save_json_atomic(snapshot_path, snapshot)
    save_incremental_index(backup_destination, index)

    return {
        "storage_mode": "incremental",
        "snapshot_id": snapshot_id,
        "snapshot_path": snapshot_path,
        "backup_path": snapshot_path,
        "backup_folder": os.path.dirname(snapshot_path),
        "backup_storage": storage_paths["root"],
        "index_path": storage_paths["index"],
        "files": files,
        "file_snapshot": build_history_snapshot_from_incremental_files(
            files,
            snapshot_path
        ),
        "status_counts": status_counts,
        "warnings": warnings,
        "skipped_duplicates": skipped_duplicates,
        "total_files": len(files),
        "objects_stored": status_counts.get("stored_new_object", 0),
        "objects_referenced": status_counts.get("referenced_existing_object", 0),
        "files_unchanged": status_counts.get("skipped_unchanged", 0),
        "files_not_eligible": status_counts.get("skipped_not_eligible", 0),
        "errors": status_counts.get("error", 0),
        "encryption": snapshot.get("encryption", {}),
    }


def create_versioned_backup(
    directories=None,
    backup_destination=None,
    config=None,
    now=None,
    manifest=None,
    backup_name=None,
    progress_callback=None,
    cancel_callback=None
):
    config = config or load_config()
    directories = directories or get_monitored_directories(config)
    backup_destination = resolve_configured_path(backup_destination or get_backup_destination(config))
    now = now or datetime.now()

    if not directories:
        raise ValueError("Adicione ao menos um diretorio antes de iniciar o backup.")

    day_folder = now.strftime("%Y-%m-%d")
    safe_backup_name = sanitize_backup_name(backup_name)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")

    if safe_backup_name:
        zip_name = f"{safe_backup_name}_{timestamp}.zip"
    else:
        zip_name = f"backup_{timestamp}.zip"

    target_directory = os.path.join(backup_destination, day_folder)
    os.makedirs(target_directory, exist_ok=True)

    zip_path = os.path.join(target_directory, zip_name)
    manifest = manifest if manifest is not None else build_backup_manifest(
        directories=directories,
        config=config,
        backup_destination=backup_destination
    )
    metadata_entries = []

    if os.path.exists(DATASET_PATH):
        metadata_entries.append((DATASET_PATH, os.path.join("_metadados", "files_dataset.csv")))

    all_entries = manifest + metadata_entries
    total_entries = len(all_entries)
    warnings = []

    try:
        with zipfile.ZipFile(zip_path, "w", compression=ZIP_COMPRESSION_METHOD) as archive:
            if progress_callback:
                progress_callback(0, total_entries, "Compactando arquivos...")

            for index, (source_path, archive_name) in enumerate(all_entries, start=1):
                ensure_not_cancelled(cancel_callback)

                try:
                    archive.write(source_path, arcname=archive_name)
                except OSError as error:
                    warnings.append(
                        {
                            "path": source_path,
                            "error": str(error)
                        }
                    )
                finally:
                    if progress_callback:
                        progress_callback(index, total_entries, archive_name)
    except BackupCancelledError:
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        raise

    return zip_path, warnings


def create_encrypted_snapshot_archive(
    snapshot_path,
    backup_destination,
    master_key,
    now=None,
    backup_name=None,
    user_id="",
    company_id="default",
    progress_callback=None
):
    master_key = normalize_master_key(master_key)

    if not master_key:
        return {}

    now = now or datetime.now()
    day_folder = now.strftime("%Y-%m-%d")
    safe_backup_name = sanitize_backup_name(backup_name)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    original_zip_name = (
        f"{safe_backup_name}_{timestamp}.zip"
        if safe_backup_name
        else f"backup_{timestamp}.zip"
    )
    target_directory = os.path.join(backup_destination, day_folder)
    encrypted_path = os.path.join(target_directory, f"{original_zip_name}.enc")
    temporary_zip_path = ""

    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_file:
            temporary_zip_path = temp_file.name

        export_snapshot_to_zip(
            snapshot_path,
            temporary_zip_path,
            progress_callback=progress_callback,
            user_master_key=crypto_service.b64encode(master_key),
        )
        backup_key = crypto_service.generate_key()
        encrypted_file = crypto_service.encrypt_file(
            temporary_zip_path,
            encrypted_path,
            backup_key,
            b"encrypted-backup-archive",
        )
        encrypted_backup_key = crypto_service.encrypt_key(
            master_key,
            backup_key,
            b"encrypted-backup-archive-key",
        )
        return {
            "backup_id": os.path.splitext(os.path.basename(snapshot_path))[0],
            "user_id": user_id,
            "company_id": company_id,
            "original_zip_name": original_zip_name,
            "encrypted_file_path": encrypted_path,
            "encryption_algorithm": crypto_service.ENCRYPTION_ALGORITHM,
            "encrypted_backup_key": encrypted_backup_key["encrypted_key"],
            "backup_key_nonce": encrypted_backup_key["key_nonce"],
            "file_nonce": encrypted_file["file_nonce"],
            "auth_tag": encrypted_file["auth_tag"],
            "compacted_size_bytes": os.path.getsize(encrypted_path),
        }
    finally:
        if temporary_zip_path and os.path.exists(temporary_zip_path):
            try:
                os.remove(temporary_zip_path)
            except OSError:
                pass


def load_history():
    return load_json(HISTORY_PATH, [])


def append_history(entry):
    history = load_history()
    history.append(entry)
    save_json(HISTORY_PATH, history[-50:])


def run_backup_job(
    directories=None,
    backup_destination=None,
    trigger="manual",
    username=None,
    user_role=None,
    company_id=None,
    user_master_key=None,
    backup_name=None,
    backup_description=None,
    now=None,
    run_scan_first=True,
    progress_callback=None,
    cancel_callback=None
):
    config = load_config()
    directories = directories or get_monitored_directories(config)
    base_backup_destination = resolve_configured_path(
        backup_destination or get_backup_destination(config)
    )
    effective_username = username or "sistema"
    effective_company_id = company_id or "default"
    backup_destination = get_user_backup_destination(
        base_backup_destination,
        effective_username
    )
    started_at = now or datetime.now()
    first_incremental_backup = is_first_incremental_backup(backup_destination)

    if progress_callback:
        progress_callback(0, "Iniciando backup...")

    ensure_not_cancelled(cancel_callback)

    if run_scan_first:
        from scanner.scanner import run_scanner

        if progress_callback:
            if first_incremental_backup:
                progress_callback(5, "Mapeando arquivos do primeiro backup...")
            else:
                progress_callback(5, "Executando scanner...")

        run_scanner(
            should_cancel=cancel_callback,
            progress_callback=progress_callback,
            classify_files=False,
        )

        if progress_callback:
            progress_callback(
                35,
                "Arquivos mapeados. Classificacao sera feita em segundo plano."
            )

    ensure_not_cancelled(cancel_callback)

    previous_snapshot = get_latest_history_snapshot(
        username=effective_username,
        company_id=effective_company_id
    )

    if progress_callback:
        progress_callback(40, "Criando snapshot incremental...")

    def on_incremental_progress(processed, total, current_entry):
        if not progress_callback:
            return

        if total <= 0:
            progress_callback(95, "Finalizando backup incremental...")
            return

        percent = 40 + int((processed / total) * 55)
        progress_callback(
            min(percent, 95),
            f"Processando objetos: {processed}/{total}"
        )

    incremental_result = run_incremental_backup(
        directories=directories,
        backup_destination=backup_destination,
        config=config,
        now=started_at,
        trigger=trigger,
        progress_callback=on_incremental_progress,
        cancel_callback=cancel_callback,
        encryption_context={
            "master_key": user_master_key,
            "user_id": effective_username,
            "company_id": effective_company_id,
        } if user_master_key else None,
    )
    current_snapshot = incremental_result["file_snapshot"]
    file_changes = build_file_changes(previous_snapshot, current_snapshot)
    completed_at = started_at
    encrypted_archive = create_encrypted_snapshot_archive(
        incremental_result["snapshot_path"],
        backup_destination,
        user_master_key,
        now=completed_at,
        backup_name=backup_name,
        user_id=effective_username,
        company_id=effective_company_id,
    ) if user_master_key else {}

    history_entry = {
        "timestamp": completed_at.strftime("%d/%m/%Y %H:%M:%S"),
        "backup_file": os.path.basename(incremental_result["snapshot_path"]),
        "backup_name": backup_name or "",
        "backup_description": backup_description or "",
        "backup_path": incremental_result["snapshot_path"],
        "backup_base_destination": base_backup_destination,
        "backup_user_directory": backup_destination,
        "encrypted_file_path": encrypted_archive.get("encrypted_file_path", ""),
        "original_zip_name": encrypted_archive.get("original_zip_name", ""),
        "backup_folder": incremental_result["backup_folder"],
        "snapshot_id": incremental_result["snapshot_id"],
        "snapshot_path": incremental_result["snapshot_path"],
        "backup_storage": incremental_result["backup_storage"],
        "storage_mode": "incremental",
        "total_files": incremental_result["total_files"],
        "objects_stored": incremental_result["objects_stored"],
        "objects_referenced": incremental_result["objects_referenced"],
        "files_unchanged": incremental_result["files_unchanged"],
        "files_not_eligible": incremental_result["files_not_eligible"],
        "duplicate_files_skipped": len(incremental_result["skipped_duplicates"]),
        "trigger": trigger,
        "user": effective_username,
        "user_role": user_role or "system",
        "company_id": effective_company_id,
        "encrypted": bool(incremental_result.get("encryption") or encrypted_archive),
        "encryption_algorithm": encrypted_archive.get(
            "encryption_algorithm",
            crypto_service.ENCRYPTION_ALGORITHM if incremental_result.get("encryption") else ""
        ),
        "backup_encryption": encrypted_archive,
        "compacted_size_bytes": encrypted_archive.get("compacted_size_bytes"),
        "file_changes": file_changes,
        "file_snapshot": current_snapshot,
        "status_counts": incremental_result["status_counts"],
        "warnings_count": len(incremental_result["warnings"]),
        "history_group_type": "full",
    }
    append_history(history_entry)

    if progress_callback:
        progress_callback(100, "Backup incremental concluido.")

    if run_scan_first:
        start_background_classification_scan()

    history_entry["warnings"] = incremental_result["warnings"]
    history_entry["skipped_duplicates"] = incremental_result["skipped_duplicates"]

    return history_entry


def run_priority_backup_job(
    directories=None,
    backup_destination=None,
    trigger="politica_prioridade",
    username=None,
    user_role=None,
    company_id=None,
    user_master_key=None,
    now=None,
    run_scan_first=True,
    progress_callback=None,
    cancel_callback=None
):
    config = load_config()

    if not is_priority_backup_policy_enabled(config):
        return {
            "skipped": True,
            "reason": "Politica de backup por prioridade desativada."
        }

    directories = directories or get_monitored_directories(config)
    base_backup_destination = resolve_configured_path(
        backup_destination or get_backup_destination(config)
    )
    effective_username = username or "sistema"
    effective_company_id = company_id or "default"
    backup_destination = get_user_backup_destination(
        base_backup_destination,
        effective_username
    )
    started_at = now or datetime.now()

    if progress_callback:
        progress_callback(0, "Verificando politica de prioridade...")

    ensure_not_cancelled(cancel_callback)

    if run_scan_first:
        from scanner.scanner import run_scanner

        if progress_callback:
            progress_callback(5, "Atualizando classificacao dos arquivos...")

        run_scanner(
            should_cancel=cancel_callback,
            progress_callback=progress_callback
        )

    ensure_not_cancelled(cancel_callback)

    previous_snapshot = get_latest_history_snapshot(
        username=effective_username,
        company_id=effective_company_id
    )
    priority_index = load_dataset_priority_index()
    incremental_index = load_incremental_index(backup_destination)
    eligible_manifest, priority_decisions, priority_index = build_priority_eligible_manifest(
        directories=directories,
        config=config,
        backup_destination=backup_destination,
        now=started_at,
        priority_index=priority_index,
        index=incremental_index,
    )

    if not eligible_manifest:
        if progress_callback:
            progress_callback(100, "Nenhum arquivo elegivel pela politica de prioridade.")

        return {
            "skipped": True,
            "reason": "Nenhum arquivo elegivel pela politica de prioridade.",
            "trigger": trigger,
            "priority_decisions": priority_decisions,
        }

    if progress_callback:
        progress_callback(40, "Criando snapshot incremental por prioridade.")

    def on_incremental_progress(processed, total, current_entry):
        if not progress_callback:
            return

        if total <= 0:
            progress_callback(95, "Finalizando snapshot por prioridade...")
            return

        percent = 40 + int((processed / total) * 55)
        progress_callback(
            min(percent, 95),
            f"Avaliando prioridade: {processed}/{total}"
        )

    incremental_result = run_incremental_backup(
        directories=directories,
        backup_destination=backup_destination,
        config=config,
        now=started_at,
        manifest=eligible_manifest,
        priority_policy=True,
        priority_index=priority_index,
        trigger=trigger,
        progress_callback=on_incremental_progress,
        cancel_callback=cancel_callback,
        encryption_context={
            "master_key": user_master_key,
            "user_id": effective_username,
            "company_id": effective_company_id,
        } if user_master_key else None,
    )
    current_snapshot = incremental_result["file_snapshot"]
    file_changes = build_file_changes(
        previous_snapshot,
        current_snapshot,
        detect_deletions=False
    )
    completed_at = started_at
    parent_entry = get_latest_full_history_entry(
        username=effective_username,
        company_id=effective_company_id
    )
    parent_snapshot_id = parent_entry.get("snapshot_id", "") if parent_entry else ""
    encrypted_archive = create_encrypted_snapshot_archive(
        incremental_result["snapshot_path"],
        backup_destination,
        user_master_key,
        now=completed_at,
        backup_name="prioridade",
        user_id=effective_username,
        company_id=effective_company_id,
    ) if user_master_key else {}

    history_entry = {
        "timestamp": completed_at.strftime("%d/%m/%Y %H:%M:%S"),
        "backup_file": os.path.basename(incremental_result["snapshot_path"]),
        "backup_name": "prioridade",
        "backup_description": "Backup automatico pela politica de prioridade.",
        "backup_path": incremental_result["snapshot_path"],
        "backup_base_destination": base_backup_destination,
        "backup_user_directory": backup_destination,
        "encrypted_file_path": encrypted_archive.get("encrypted_file_path", ""),
        "original_zip_name": encrypted_archive.get("original_zip_name", ""),
        "backup_folder": incremental_result["backup_folder"],
        "snapshot_id": incremental_result["snapshot_id"],
        "snapshot_path": incremental_result["snapshot_path"],
        "backup_storage": incremental_result["backup_storage"],
        "storage_mode": "incremental",
        "total_files": incremental_result["total_files"],
        "objects_stored": incremental_result["objects_stored"],
        "objects_referenced": incremental_result["objects_referenced"],
        "files_unchanged": incremental_result["files_unchanged"],
        "files_not_eligible": incremental_result["files_not_eligible"],
        "duplicate_files_skipped": len(incremental_result["skipped_duplicates"]),
        "trigger": trigger,
        "user": effective_username,
        "user_role": user_role or "system",
        "company_id": effective_company_id,
        "encrypted": bool(incremental_result.get("encryption") or encrypted_archive),
        "encryption_algorithm": encrypted_archive.get(
            "encryption_algorithm",
            crypto_service.ENCRYPTION_ALGORITHM if incremental_result.get("encryption") else ""
        ),
        "backup_encryption": encrypted_archive,
        "compacted_size_bytes": encrypted_archive.get("compacted_size_bytes"),
        "file_changes": file_changes,
        "file_snapshot": current_snapshot,
        "status_counts": incremental_result["status_counts"],
        "warnings_count": len(incremental_result["warnings"]),
        "priority_policy": True,
        "partial_backup": True,
        "priority_decisions": priority_decisions,
        "history_group_type": "priority_snapshot",
        "parent_snapshot_id": parent_snapshot_id,
        "priority_scope": determine_priority_scope(eligible_manifest, priority_index),
    }
    append_history(history_entry)

    if progress_callback:
        progress_callback(100, "Backup incremental por prioridade concluido.")

    history_entry["warnings"] = incremental_result["warnings"]
    history_entry["skipped_duplicates"] = incremental_result["skipped_duplicates"]

    return history_entry


def load_schedule():
    return load_json(SCHEDULE_PATH, {})


def save_schedule(schedule):
    save_json(SCHEDULE_PATH, schedule)


def parse_schedule_time(value):
    if not value:
        return None

    try:
        return datetime.strptime(str(value).strip(), "%H:%M").time()
    except ValueError:
        return None


def is_time_within_window(current_time, start_time, end_time):
    if start_time is None or end_time is None:
        return False

    if start_time <= end_time:
        return start_time <= current_time <= end_time

    return current_time >= start_time or current_time <= end_time


def is_schedule_due(now=None):
    now = now or datetime.now()
    schedule = load_schedule()

    if not schedule:
        return False

    start_time = parse_schedule_time(
        schedule.get("time_start") or schedule.get("time")
    )
    end_time = parse_schedule_time(
        schedule.get("time_end") or schedule.get("time")
    )

    if not is_time_within_window(now.time(), start_time, end_time):
        return False

    last_run_at = schedule.get("last_run_at")

    if not last_run_at:
        return True

    try:
        last_run = datetime.fromisoformat(last_run_at)
    except ValueError:
        return True

    return last_run.date() != now.date()


def mark_schedule_executed(now=None):
    now = now or datetime.now()
    schedule = load_schedule()

    if not schedule:
        return

    schedule["last_run_at"] = now.isoformat(timespec="seconds")
    save_schedule(schedule)


def normalize_archive_name(archive_name):
    if not archive_name:
        return ""

    return str(archive_name).replace("\\", "/").strip("/")


def calculate_zip_member_hash(archive, member_info, chunk_size=65536):
    hasher = hashlib.sha256()

    with archive.open(member_info, "r") as file:
        while True:
            chunk = file.read(chunk_size)

            if not chunk:
                break

            hasher.update(chunk)

    return hasher.hexdigest()


def build_recovered_file_path(path):
    directory = os.path.dirname(path)
    filename = os.path.basename(path)
    name, extension = os.path.splitext(filename)

    if not name:
        name = filename
        extension = ""

    base_path = os.path.join(directory, f"{name}_recuperado{extension}")
    candidate_path = base_path
    counter = 2

    while os.path.exists(candidate_path):
        candidate_path = os.path.join(
            directory,
            f"{name}_recuperado_{counter}{extension}"
        )
        counter += 1

    return candidate_path


def build_recovered_folder_path(path):
    normalized_path = normalize_path(path)
    parent_directory = os.path.dirname(normalized_path)
    folder_name = os.path.basename(normalized_path.rstrip("\\/"))
    base_path = os.path.join(parent_directory, f"{folder_name}_recuperado")
    candidate_path = base_path
    counter = 2

    while os.path.exists(candidate_path):
        candidate_path = os.path.join(
            parent_directory,
            f"{folder_name}_recuperado_{counter}"
        )
        counter += 1

    return candidate_path


def get_snapshot_storage_root(snapshot_path, snapshot):
    storage_root = snapshot.get("storage_root", "")

    if storage_root:
        if os.path.isabs(storage_root):
            return normalize_path(storage_root)

        return normalize_path(os.path.join(os.path.dirname(snapshot_path), storage_root))

    snapshots_directory = os.path.dirname(normalize_path(snapshot_path))
    return os.path.dirname(snapshots_directory)


def build_safe_restore_path(restore_destination, archive_name, fallback_name):
    parts = [
        part
        for part in normalize_archive_name(archive_name).split("/")
        if part and part not in {".", ".."}
    ]

    if not parts:
        parts = [fallback_name or "arquivo_restaurado"]

    parts = [part.replace(":", "") for part in parts]
    destination = normalize_path(restore_destination)
    target_path = normalize_path(os.path.join(destination, *parts))

    try:
        if os.path.commonpath([destination, target_path]) != destination:
            return os.path.join(destination, parts[-1])
    except ValueError:
        return os.path.join(destination, parts[-1])

    return target_path


def restore_snapshot(
    snapshot_path,
    restore_destination,
    overwrite=False,
    conflict_strategy="rename",
    user_master_key=None
):
    snapshot_path = normalize_path(snapshot_path)
    restore_destination = normalize_path(restore_destination)
    snapshot = load_json(snapshot_path, {})

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("files"), list):
        raise ValueError("Snapshot incremental invalido.")

    storage_root = get_snapshot_storage_root(snapshot_path, snapshot)
    results = []

    for file_data in snapshot.get("files", []):
        archive_name = file_data.get("archive_name", "")
        object_path = file_data.get("object_path", "")
        file_hash = file_data.get("hash") or file_data.get("file_hash", "")
        target_path = build_safe_restore_path(
            restore_destination,
            archive_name,
            file_data.get("file_name", "")
        )
        original_target_path = target_path
        result = {
            "name": file_data.get("file_name", ""),
            "archive_name": archive_name,
            "target_path": target_path,
            "status": "error",
            "message": "",
            "backup_path": snapshot_path,
            "object_path": object_path,
        }

        if file_data.get("status") == "error" or not object_path or not file_hash:
            result["status"] = "not_found"
            result["message"] = "Entrada sem objeto restauravel no snapshot."
            results.append(result)
            continue

        object_abs_path = resolve_storage_relative_path(storage_root, object_path)

        if not os.path.exists(object_abs_path):
            result["status"] = "not_found"
            result["message"] = "Objeto nao encontrado no armazenamento incremental."
            results.append(result)
            log_backup_decision("ERROR", f"Objeto nao encontrado: {object_abs_path}")
            continue

        try:
            if os.path.exists(target_path):
                is_identical = (
                    os.path.isfile(target_path)
                    and calculate_file_hash(target_path) == file_hash
                )

                if is_identical and not overwrite:
                    result["status"] = "identical_existing"
                    result["message"] = "Arquivo existente tem o mesmo conteudo."
                    results.append(result)
                    continue

                if not overwrite:
                    if conflict_strategy == "rename":
                        target_path = build_recovered_file_path(target_path)
                        result["target_path"] = target_path
                    else:
                        result["status"] = "skipped_existing"
                        result["message"] = "Destino ja existe."
                        results.append(result)
                        continue

            target_directory = os.path.dirname(target_path)

            if target_directory:
                os.makedirs(target_directory, exist_ok=True)

            decrypt_storage_object_to_path(
                object_abs_path,
                target_path,
                file_data.get("encryption"),
                user_master_key,
            )
            modified_at = parse_iso_datetime(file_data.get("modified_at", ""))

            if modified_at:
                timestamp = modified_at.timestamp()
                os.utime(target_path, (timestamp, timestamp))

            if target_path != original_target_path:
                result["status"] = "restored_renamed"
                result["message"] = "Arquivo restaurado com outro nome."
            else:
                result["status"] = "restored"
                result["message"] = "Arquivo restaurado."

            log_backup_decision("INFO", f"Arquivo restaurado do snapshot: {target_path}")
        except (OSError, ValueError, crypto_service.CryptoError) as error:
            result["message"] = str(error)
            log_backup_decision(
                "ERROR",
                f"Falha ao restaurar {archive_name}: {error}"
            )

        results.append(result)

    return results


def export_snapshot_to_zip(
    snapshot_path,
    destination_zip_path,
    progress_callback=None,
    user_master_key=None
):
    snapshot_path = normalize_path(snapshot_path)
    destination_zip_path = normalize_path(destination_zip_path)
    snapshot = load_json(snapshot_path, {})

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("files"), list):
        raise ValueError("Snapshot incremental invalido.")

    storage_root = get_snapshot_storage_root(snapshot_path, snapshot)
    destination_directory = os.path.dirname(destination_zip_path)

    if destination_directory:
        os.makedirs(destination_directory, exist_ok=True)

    warnings = []
    exported_count = 0
    exportable_files = [
        file_data
        for file_data in snapshot.get("files", [])
        if (
            normalize_archive_name(file_data.get("archive_name", ""))
            and file_data.get("object_path", "")
            and (file_data.get("hash") or file_data.get("file_hash", ""))
            and file_data.get("status") != "error"
        )
    ]
    total_files = len(exportable_files)

    if progress_callback:
        progress_callback(0, total_files, "Preparando exportacao do backup...")

    with zipfile.ZipFile(destination_zip_path, "w", compression=ZIP_COMPRESSION_METHOD) as archive:
        for item_index, file_data in enumerate(exportable_files, start=1):
            archive_name = normalize_archive_name(file_data.get("archive_name", ""))
            object_path = file_data.get("object_path", "")
            file_hash = file_data.get("hash") or file_data.get("file_hash", "")

            object_abs_path = resolve_storage_relative_path(storage_root, object_path)

            if not os.path.exists(object_abs_path):
                warnings.append(
                    {
                        "archive_name": archive_name,
                        "error": "Objeto nao encontrado no armazenamento incremental."
                    }
                )
                log_backup_decision(
                    "ERROR",
                    f"Objeto ausente durante exportacao do ZIP: {object_abs_path}"
                )
                if progress_callback:
                    progress_callback(item_index, total_files, archive_name)
                continue

            try:
                encryption_metadata = file_data.get("encryption")

                # Sempre descomprimir os dados antes de adicionar ao ZIP
                # (objetos estao armazenados comprimidos com zstd)
                raw_data = read_storage_object_bytes(
                    object_abs_path,
                    encryption_metadata,
                    user_master_key,
                )
                archive.writestr(archive_name, raw_data)

                exported_count += 1
            except (OSError, ValueError, crypto_service.CryptoError) as error:
                warnings.append(
                    {
                        "archive_name": archive_name,
                        "error": str(error)
                    }
                )
                log_backup_decision(
                    "ERROR",
                    f"Falha ao adicionar arquivo ao ZIP exportado: {archive_name} ({error})"
                )

            if progress_callback:
                progress_callback(item_index, total_files, archive_name)

    return {
        "zip_path": destination_zip_path,
        "files_exported": exported_count,
        "warnings": warnings,
    }


def find_snapshot_file_entry(file_snapshot, archive_name):
    target_name = normalize_archive_name(archive_name)

    if not target_name or not isinstance(file_snapshot, dict):
        return None

    direct_entry = file_snapshot.get(target_name)

    if direct_entry:
        return direct_entry

    target_name_lower = target_name.lower()

    for current_name, file_data in file_snapshot.items():
        if normalize_archive_name(current_name).lower() == target_name_lower:
            return file_data

    return None


def find_incremental_history_object(entry, archive_name):
    if not isinstance(entry, dict) or entry.get("storage_mode") != "incremental":
        return None

    file_data = find_snapshot_file_entry(entry.get("file_snapshot", {}), archive_name)

    if not file_data:
        return None

    object_path = file_data.get("object_path", "")

    if not object_path:
        return None

    storage_root = entry.get("backup_storage", "")
    snapshot_path = entry.get("snapshot_path") or entry.get("backup_path", "")

    if not storage_root and snapshot_path:
        snapshot = load_json(snapshot_path, {})
        storage_root = get_snapshot_storage_root(snapshot_path, snapshot)

    if not storage_root:
        return None

    object_abs_path = resolve_storage_relative_path(storage_root, object_path)

    if not os.path.exists(object_abs_path):
        return None

    return {
        "storage_mode": "incremental",
        "object_path": object_abs_path,
        "snapshot_path": snapshot_path,
        "history_entry": entry,
        "file_data": file_data,
    }


def iter_history_backup_paths(entry, backup_destination=None):
    if not isinstance(entry, dict):
        return

    backup_file = entry.get("backup_file", "")
    direct_path = entry.get("backup_path", "")
    backup_folder = entry.get("backup_folder", "")
    seen_paths = set()

    def yield_if_zip(path):
        if not path or not str(path).lower().endswith(".zip"):
            return

        normalized_path = normalize_path(path)

        if normalized_path in seen_paths:
            return

        if os.path.exists(normalized_path):
            seen_paths.add(normalized_path)
            yield normalized_path

    for path in yield_if_zip(direct_path):
        yield path

    search_roots = [
        backup_folder,
        backup_destination,
        get_backup_destination(),
        DEFAULT_BACKUP_DIR,
    ]

    if direct_path:
        search_roots.append(os.path.dirname(direct_path))

    for root in search_roots:
        if not root:
            continue

        root = resolve_configured_path(root)

        if not os.path.isdir(root):
            continue

        if backup_file and str(backup_file).lower().endswith(".zip"):
            for current_root, _, names in os.walk(root):
                for name in names:
                    if name != backup_file:
                        continue

                    for path in yield_if_zip(os.path.join(current_root, name)):
                        yield path


def find_zip_member(archive, archive_name):
    target_name = normalize_archive_name(archive_name)

    if not target_name:
        return None

    target_name_lower = target_name.lower()
    fallback_member = None

    for info in archive.infolist():
        if info.is_dir():
            continue

        member_name = normalize_archive_name(info.filename)

        if member_name == target_name:
            return info.filename

        if member_name.lower() == target_name_lower:
            fallback_member = info.filename

    return fallback_member


def find_backup_containing_archive(
    archive_name,
    before_history_index=None,
    backup_destination=None,
    history=None
):
    history = history if history is not None else load_history()
    indexed_history = list(enumerate(history))

    if before_history_index is not None:
        indexed_history = [
            (index, entry)
            for index, entry in indexed_history
            if index < before_history_index
        ]

    for history_index, entry in reversed(indexed_history):
        incremental_source = find_incremental_history_object(entry, archive_name)

        if incremental_source:
            incremental_source["history_index"] = history_index
            return incremental_source

        for backup_path in iter_history_backup_paths(entry, backup_destination):
            try:
                with zipfile.ZipFile(backup_path, "r") as archive:
                    member_name = find_zip_member(archive, archive_name)
            except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
                continue

            if member_name:
                return {
                    "backup_path": backup_path,
                    "member_name": member_name,
                    "history_index": history_index,
                    "history_entry": entry,
                }

    return None


def build_restore_target(change):
    source_path = change.get("source_path", "")

    if source_path:
        return normalize_path(source_path)

    archive_name = normalize_archive_name(change.get("archive_name", ""))

    if not archive_name:
        return ""

    return normalize_path(os.path.join(PROJECT_ROOT, "restaurados", archive_name))


def inspect_restore_change(
    change,
    before_history_index=None,
    backup_destination=None
):
    archive_name = change.get("archive_name", "")
    target_path = build_restore_target(change)
    result = {
        "name": change.get("name", ""),
        "archive_name": archive_name,
        "target_path": target_path,
        "status": "error",
        "message": "",
        "backup_path": "",
    }

    if not archive_name:
        result["message"] = "Entrada sem caminho interno no backup."
        return result

    if not target_path:
        result["message"] = "Entrada sem caminho de destino."
        return result

    backup_source = find_backup_containing_archive(
        archive_name,
        before_history_index=before_history_index,
        backup_destination=backup_destination
    )

    if not backup_source:
        result["status"] = "not_found"
        result["message"] = "Arquivo nao encontrado em backups anteriores."
        return result

    result["backup_path"] = (
        backup_source.get("backup_path")
        or backup_source.get("snapshot_path")
        or backup_source.get("object_path", "")
    )

    if backup_source.get("storage_mode") == "incremental":
        if not os.path.exists(target_path):
            result["status"] = "target_missing"
            result["message"] = "Destino livre."
            return result

        if not os.path.isfile(target_path):
            result["status"] = "different_existing"
            result["message"] = "Ja existe um item no destino com este nome."
            return result

        try:
            backup_hash = (
                backup_source.get("file_data", {}).get("file_hash")
                or calculate_file_hash(backup_source["object_path"])
            )
            existing_hash = calculate_file_hash(target_path)
        except (OSError, ValueError, crypto_service.CryptoError) as error:
            result["message"] = str(error)
            return result

        if backup_hash == existing_hash:
            result["status"] = "identical_existing"
            result["message"] = "Arquivo existente tem o mesmo conteudo."
        else:
            result["status"] = "different_existing"
            result["message"] = "Arquivo existente tem conteudo diferente."

        return result

    if not os.path.exists(target_path):
        result["status"] = "target_missing"
        result["message"] = "Destino livre."
        return result

    if not os.path.isfile(target_path):
        result["status"] = "different_existing"
        result["message"] = "Ja existe um item no destino com este nome."
        return result

    try:
        with zipfile.ZipFile(backup_source["backup_path"], "r") as archive:
            member_info = archive.getinfo(backup_source["member_name"])
            backup_hash = calculate_zip_member_hash(archive, member_info)

        existing_hash = calculate_file_hash(target_path)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, KeyError) as error:
        result["message"] = str(error)
        return result

    if backup_hash == existing_hash:
        result["status"] = "identical_existing"
        result["message"] = "Arquivo existente tem o mesmo conteudo."
    else:
        result["status"] = "different_existing"
        result["message"] = "Arquivo existente tem conteudo diferente."

    return result


def inspect_restore_changes(
    changes,
    before_history_index=None,
    backup_destination=None
):
    return [
        inspect_restore_change(
            change,
            before_history_index=before_history_index,
            backup_destination=backup_destination
        )
        for change in changes
        if change.get("action") in RECOVERABLE_ACTIONS
    ]


def restore_recoverable_change(
    change,
    before_history_index=None,
    backup_destination=None,
    overwrite=False,
    conflict_strategy="skip",
    target_path_override=None,
    user_master_key=None
):
    archive_name = change.get("archive_name", "")
    original_target_path = build_restore_target(change)
    target_path = normalize_path(target_path_override) if target_path_override else original_target_path
    result = {
        "name": change.get("name", ""),
        "archive_name": archive_name,
        "target_path": target_path,
        "original_target_path": original_target_path,
        "status": "error",
        "message": "",
        "backup_path": "",
    }

    if not archive_name:
        result["message"] = "Entrada sem caminho interno no backup."
        return result

    if not original_target_path or not target_path:
        result["message"] = "Entrada sem caminho de destino."
        return result

    backup_source = find_backup_containing_archive(
        archive_name,
        before_history_index=before_history_index,
        backup_destination=backup_destination
    )

    if not backup_source:
        result["status"] = "not_found"
        result["message"] = "Arquivo nao encontrado em backups anteriores."
        return result

    result["backup_path"] = (
        backup_source.get("backup_path")
        or backup_source.get("snapshot_path")
        or backup_source.get("object_path", "")
    )

    if backup_source.get("storage_mode") == "incremental":
        object_path = backup_source["object_path"]

        try:
            if os.path.exists(target_path):
                is_identical = False

                if os.path.isfile(target_path):
                    existing_hash = calculate_file_hash(target_path)
                    backup_hash = (
                        backup_source.get("file_data", {}).get("file_hash")
                        or calculate_file_hash(object_path)
                    )
                    is_identical = existing_hash == backup_hash

                if is_identical and not overwrite:
                    result["status"] = "identical_existing"
                    result["message"] = "Arquivo existente tem o mesmo conteudo."
                    return result

                if not overwrite:
                    if conflict_strategy == "rename":
                        target_path = build_recovered_file_path(target_path)
                        result["target_path"] = target_path
                    else:
                        result["status"] = "skipped_existing"
                        result["message"] = "Destino ja existe."
                        return result

            target_directory = os.path.dirname(target_path)

            if target_directory:
                os.makedirs(target_directory, exist_ok=True)

            decrypt_storage_object_to_path(
                object_path,
                target_path,
                backup_source.get("file_data", {}).get("encryption"),
                user_master_key,
            )
            modified_at = parse_iso_datetime(
                backup_source.get("file_data", {}).get("modified_at", "")
            )

            if modified_at:
                timestamp = modified_at.timestamp()
                os.utime(target_path, (timestamp, timestamp))
        except OSError as error:
            result["message"] = str(error)
            return result

        if target_path != original_target_path:
            result["status"] = "restored_renamed"
            result["message"] = "Arquivo recuperado com outro nome."
        else:
            result["status"] = "restored"
            result["message"] = "Arquivo recuperado."

        return result

    try:
        with zipfile.ZipFile(backup_source["backup_path"], "r") as archive:
            member_info = archive.getinfo(backup_source["member_name"])

            if os.path.exists(target_path):
                is_identical = False

                if os.path.isfile(target_path):
                    existing_hash = calculate_file_hash(target_path)
                    backup_hash = calculate_zip_member_hash(archive, member_info)
                    is_identical = existing_hash == backup_hash

                if is_identical and not overwrite:
                    result["status"] = "identical_existing"
                    result["message"] = "Arquivo existente tem o mesmo conteudo."
                    return result

                if not overwrite:
                    if conflict_strategy == "rename":
                        target_path = build_recovered_file_path(target_path)
                        result["target_path"] = target_path
                    else:
                        result["status"] = "skipped_existing"
                        result["message"] = "Destino ja existe."
                        return result

            target_directory = os.path.dirname(target_path)

            if target_directory:
                os.makedirs(target_directory, exist_ok=True)

            with archive.open(member_info, "r") as source_file:
                with open(target_path, "wb") as target_file:
                    shutil.copyfileobj(source_file, target_file)

            try:
                modified_at = datetime(*member_info.date_time).timestamp()
                os.utime(target_path, (modified_at, modified_at))
            except (OSError, ValueError):
                pass
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, KeyError) as error:
        result["message"] = str(error)
        return result

    if target_path != original_target_path:
        result["status"] = "restored_renamed"
        result["message"] = "Arquivo recuperado com outro nome."
    else:
        result["status"] = "restored"
        result["message"] = "Arquivo recuperado."

    return result


def restore_recoverable_changes(
    changes,
    before_history_index=None,
    backup_destination=None,
    overwrite=False,
    conflict_strategy="skip",
    target_overrides=None,
    user_master_key=None
):
    results = []
    target_overrides = target_overrides or {}
    normalized_overrides = {
        normalize_archive_name(archive_name): target_path
        for archive_name, target_path in target_overrides.items()
    }

    for change in changes:
        if change.get("action") not in RECOVERABLE_ACTIONS:
            continue

        archive_name = normalize_archive_name(change.get("archive_name", ""))

        results.append(
            restore_recoverable_change(
                change,
                before_history_index=before_history_index,
                backup_destination=backup_destination,
                overwrite=overwrite,
                conflict_strategy=conflict_strategy,
                target_path_override=normalized_overrides.get(archive_name),
                user_master_key=user_master_key,
            )
        )

    return results


def restore_deleted_change(*args, **kwargs):
    return restore_recoverable_change(*args, **kwargs)


def restore_deleted_changes(*args, **kwargs):
    return restore_recoverable_changes(*args, **kwargs)


def get_latest_backup_path(backup_destination=None):
    base_directory = resolve_configured_path(backup_destination or get_backup_destination())

    for entry in reversed(load_history()):
        backup_path = entry.get("backup_path") or entry.get("snapshot_path")

        if backup_path and os.path.exists(backup_path):
            return normalize_path(backup_path)

    if not os.path.exists(base_directory):
        return None

    files = []

    for root, _, names in os.walk(base_directory):
        for name in names:
            lower_name = name.lower()

            if lower_name.endswith(".zip") or (
                lower_name.endswith(".json")
                and os.path.basename(root).lower() == SNAPSHOTS_DIRNAME
            ):
                files.append(os.path.join(root, name))

    if not files:
        return None

    return max(files, key=os.path.getmtime)
