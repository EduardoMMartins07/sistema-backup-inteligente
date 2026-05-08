import hashlib
import csv
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from datetime import timedelta
from utils.file_hash import calculate_file_hash

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "config.json")
DATASET_PATH = os.path.join(PROJECT_ROOT, "dataset", "files_dataset.csv")
DEFAULT_BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")
HISTORY_PATH = os.path.join(PROJECT_ROOT, "config", "backup_history.json")
SCHEDULE_PATH = os.path.join(PROJECT_ROOT, "config", "backup_schedule.json")
PRIORITY_STATE_PATH = os.path.join(PROJECT_ROOT, "config", "priority_backup_state.json")
ZIP_COMPRESSION_METHOD = zipfile.ZIP_LZMA
RECOVERABLE_ACTIONS = {"alterado", "excluido"}
PRIORITY_LOW = "baixa"
PRIORITY_MEDIUM = "media"
PRIORITY_HIGH = "alta"
PRIORITY_INTERVALS = {
    PRIORITY_LOW: timedelta(days=7),
    PRIORITY_MEDIUM: timedelta(days=2),
    PRIORITY_HIGH: timedelta(hours=4),
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


def is_deduplication_enabled(config=None):
    config = config or load_config()
    return bool(config.get("deduplicate_backup", False))


def is_priority_backup_policy_enabled(config=None):
    config = config or load_config()
    return bool(config.get("priority_backup_policy_enabled", False))


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

    if not last_backup_at:
        return True, "primeiro backup pela politica de prioridade"

    if priority == PRIORITY_HIGH:
        today = now.date().isoformat()

        if state_entry.get("last_daily_backup_date") != today:
            return True, "primeiro backup de alta prioridade no dia"

        if now - last_backup_at >= PRIORITY_INTERVALS[PRIORITY_HIGH] and hash_changed:
            return True, "arquivo de alta prioridade alterado no intervalo de 4 horas"

        return False, "alta prioridade ainda dentro do intervalo"

    interval = PRIORITY_INTERVALS.get(priority, PRIORITY_INTERVALS[PRIORITY_LOW])

    if now - last_backup_at >= interval:
        return True, f"intervalo vencido para prioridade {priority}"

    return False, f"prioridade {priority} ainda dentro do intervalo"


def build_priority_backup_manifest(
    directories=None,
    config=None,
    backup_destination=None,
    now=None
):
    now = now or datetime.now()
    config = config or load_config()
    backup_destination = backup_destination or get_backup_destination(config)
    full_manifest = build_backup_manifest(
        directories=directories,
        config=config,
        backup_destination=backup_destination
    )
    priority_index = load_dataset_priority_index()
    priority_state = load_priority_state()
    due_manifest = []
    decisions = []

    for source_path, archive_name in full_manifest:
        metadata = find_priority_metadata(source_path, archive_name, priority_index)
        priority = normalize_priority(metadata.get("priority"))
        state_key = normalize_path(source_path)
        include_file, reason = should_include_priority_file(
            source_path,
            archive_name,
            metadata,
            priority_state.get(state_key, {}),
            now
        )

        decisions.append(
            {
                "source_path": source_path,
                "archive_name": archive_name,
                "priority": priority,
                "included": include_file,
                "reason": reason,
            }
        )

        if include_file:
            due_manifest.append((source_path, archive_name))

    return due_manifest, decisions, priority_index


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


def get_latest_history_snapshot(include_partial=False):
    history = load_history()

    for entry in reversed(history):
        if entry.get("partial_backup") and not include_partial:
            continue

        snapshot = entry.get("file_snapshot")

        if isinstance(snapshot, dict):
            return snapshot

    return {}


def build_file_changes(previous_snapshot, current_snapshot):
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
            }
        )

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
    backup_name=None,
    backup_description=None,
    run_scan_first=True,
    progress_callback=None,
    cancel_callback=None
):
    config = load_config()
    directories = directories or get_monitored_directories(config)
    backup_destination = resolve_configured_path(backup_destination or get_backup_destination(config))

    if progress_callback:
        progress_callback(0, "Iniciando backup...")

    ensure_not_cancelled(cancel_callback)

    if run_scan_first:
        from scanner.scanner import run_scanner

        if progress_callback:
            progress_callback(5, "Executando scanner...")

        run_scanner(
            should_cancel=cancel_callback,
            progress_callback=progress_callback
        )

        if progress_callback:
            progress_callback(35, "Scanner concluido.")

    ensure_not_cancelled(cancel_callback)

    manifest = build_backup_manifest(
        directories=directories,
        backup_destination=backup_destination,
        config=config
    )
    current_snapshot = build_file_snapshot(manifest)
    previous_snapshot = get_latest_history_snapshot()
    file_changes = build_file_changes(previous_snapshot, current_snapshot)
    deduplication_enabled = is_deduplication_enabled(config)
    skipped_duplicates = []
    pre_backup_warnings = []

    if deduplication_enabled:
        manifest, skipped_duplicates, pre_backup_warnings = deduplicate_manifest(manifest)

    total_files = len(manifest)

    if progress_callback:
        if deduplication_enabled:
            progress_callback(
                40,
                (
                    f"{total_files} arquivo(s) unicos prontos para compactacao. "
                    f"{len(skipped_duplicates)} duplicado(s) ignorado(s)."
                )
            )
        else:
            progress_callback(40, f"{total_files} arquivo(s) prontos para compactacao.")

    def on_zip_progress(processed, total, current_entry):
        if not progress_callback:
            return

        if total <= 0:
            progress_callback(95, "Finalizando backup...")
            return

        percent = 40 + int((processed / total) * 55)
        progress_callback(
            min(percent, 95),
            f"Compactando: {processed}/{total}"
        )

    backup_path, warnings = create_versioned_backup(
        directories=directories,
        backup_destination=backup_destination,
        config=config,
        manifest=manifest,
        backup_name=backup_name,
        progress_callback=on_zip_progress,
        cancel_callback=cancel_callback
    )
    warnings = pre_backup_warnings + warnings
    backup_folder = os.path.dirname(backup_path)
    completed_at = datetime.now()

    history_entry = {
        "timestamp": completed_at.strftime("%d/%m/%Y %H:%M:%S"),
        "backup_file": os.path.basename(backup_path),
        "backup_name": backup_name or "",
        "backup_description": backup_description or "",
        "backup_path": backup_path,
        "backup_folder": backup_folder,
        "total_files": total_files,
        "duplicate_files_skipped": len(skipped_duplicates),
        "trigger": trigger,
        "user": username or "sistema",
        "user_role": user_role or "system",
        "file_changes": file_changes,
        "file_snapshot": current_snapshot,
        "warnings_count": len(warnings)
    }
    append_history(history_entry)
    update_priority_state_after_backup(manifest, current_snapshot, completed_at)

    if progress_callback:
        progress_callback(100, "Backup concluido.")

    history_entry["warnings"] = warnings
    history_entry["skipped_duplicates"] = skipped_duplicates

    return history_entry


def run_priority_backup_job(
    directories=None,
    backup_destination=None,
    trigger="politica_prioridade",
    username=None,
    user_role=None,
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
    backup_destination = resolve_configured_path(backup_destination or get_backup_destination(config))
    started_at = datetime.now()

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

    manifest, priority_decisions, priority_index = build_priority_backup_manifest(
        directories=directories,
        config=config,
        backup_destination=backup_destination,
        now=started_at
    )

    if not manifest:
        if progress_callback:
            progress_callback(100, "Nenhum arquivo vencido pela politica de prioridade.")

        return {
            "skipped": True,
            "reason": "Nenhum arquivo vencido pela politica de prioridade.",
            "trigger": trigger,
            "priority_decisions": priority_decisions,
        }

    current_snapshot = build_file_snapshot(manifest)
    previous_snapshot = get_latest_history_snapshot()
    file_changes = build_file_changes(previous_snapshot, current_snapshot)
    deduplication_enabled = is_deduplication_enabled(config)
    skipped_duplicates = []
    pre_backup_warnings = []

    if deduplication_enabled:
        manifest, skipped_duplicates, pre_backup_warnings = deduplicate_manifest(manifest)

    total_files = len(manifest)

    if progress_callback:
        progress_callback(
            40,
            f"{total_files} arquivo(s) vencido(s) pela prioridade."
        )

    def on_zip_progress(processed, total, current_entry):
        if not progress_callback:
            return

        if total <= 0:
            progress_callback(95, "Finalizando backup por prioridade...")
            return

        percent = 40 + int((processed / total) * 55)
        progress_callback(
            min(percent, 95),
            f"Compactando por prioridade: {processed}/{total}"
        )

    backup_path, warnings = create_versioned_backup(
        directories=directories,
        backup_destination=backup_destination,
        config=config,
        manifest=manifest,
        backup_name="prioridade",
        progress_callback=on_zip_progress,
        cancel_callback=cancel_callback
    )
    warnings = pre_backup_warnings + warnings
    backup_folder = os.path.dirname(backup_path)
    completed_at = datetime.now()

    history_entry = {
        "timestamp": completed_at.strftime("%d/%m/%Y %H:%M:%S"),
        "backup_file": os.path.basename(backup_path),
        "backup_name": "prioridade",
        "backup_description": "Backup automatico pela politica de prioridade.",
        "backup_path": backup_path,
        "backup_folder": backup_folder,
        "total_files": total_files,
        "duplicate_files_skipped": len(skipped_duplicates),
        "trigger": trigger,
        "user": username or "sistema",
        "user_role": user_role or "system",
        "file_changes": file_changes,
        "file_snapshot": current_snapshot,
        "warnings_count": len(warnings),
        "partial_backup": True,
        "priority_policy": True,
        "priority_decisions": priority_decisions,
    }
    append_history(history_entry)
    update_priority_state_after_backup(
        manifest,
        current_snapshot,
        completed_at,
        priority_index=priority_index
    )

    if progress_callback:
        progress_callback(100, "Backup por prioridade concluido.")

    history_entry["warnings"] = warnings
    history_entry["skipped_duplicates"] = skipped_duplicates

    return history_entry


def load_schedule():
    return load_json(SCHEDULE_PATH, {})


def save_schedule(schedule):
    save_json(SCHEDULE_PATH, schedule)


def is_schedule_due(now=None):
    now = now or datetime.now()
    schedule = load_schedule()

    if not schedule or not schedule.get("time"):
        return False

    if now.strftime("%H:%M") != schedule.get("time"):
        return False

    last_run_at = schedule.get("last_run_at")

    if not last_run_at:
        return True

    try:
        last_run = datetime.fromisoformat(last_run_at)
    except ValueError:
        return True

    frequency = schedule.get("frequency", "Diariamente")

    if frequency == "Semanalmente":
        return last_run.isocalendar()[:2] != now.isocalendar()[:2]

    if frequency == "Mensalmente":
        return (last_run.year, last_run.month) != (now.year, now.month)

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

    result["backup_path"] = backup_source["backup_path"]

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
    target_path_override=None
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

    result["backup_path"] = backup_source["backup_path"]

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
    target_overrides=None
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
                target_path_override=normalized_overrides.get(archive_name)
            )
        )

    return results


def restore_deleted_change(*args, **kwargs):
    return restore_recoverable_change(*args, **kwargs)


def restore_deleted_changes(*args, **kwargs):
    return restore_recoverable_changes(*args, **kwargs)


def get_latest_backup_path(backup_destination=None):
    base_directory = resolve_configured_path(backup_destination or get_backup_destination())

    if not os.path.exists(base_directory):
        return None

    files = []

    for root, _, names in os.walk(base_directory):
        for name in names:
            if name.lower().endswith(".zip"):
                files.append(os.path.join(root, name))

    if not files:
        return None

    return max(files, key=os.path.getmtime)
