import json
import os
import zipfile
from datetime import datetime
from utils.file_hash import calculate_file_hash

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "config.json")
DATASET_PATH = os.path.join(PROJECT_ROOT, "dataset", "files_dataset.csv")
DEFAULT_BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")
HISTORY_PATH = os.path.join(PROJECT_ROOT, "config", "backup_history.json")
SCHEDULE_PATH = os.path.join(PROJECT_ROOT, "config", "backup_schedule.json")

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


def create_versioned_backup(
    directories=None,
    backup_destination=None,
    config=None,
    now=None,
    manifest=None,
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
    zip_name = f"backup_{now.strftime('%Y-%m-%d_%H-%M-%S')}.zip"
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
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
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
        progress_callback=on_zip_progress,
        cancel_callback=cancel_callback
    )
    warnings = pre_backup_warnings + warnings
    backup_folder = os.path.dirname(backup_path)

    history_entry = {
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "backup_file": os.path.basename(backup_path),
        "backup_path": backup_path,
        "backup_folder": backup_folder,
        "total_files": total_files,
        "duplicate_files_skipped": len(skipped_duplicates),
        "trigger": trigger,
        "warnings_count": len(warnings)
    }
    append_history(history_entry)

    if progress_callback:
        progress_callback(100, "Backup concluido.")

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
