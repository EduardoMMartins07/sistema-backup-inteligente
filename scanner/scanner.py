import json
import os
import threading
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from backup.backup_manager import BackupCancelledError
from backup.backup_manager import is_path_ignored
from backup.backup_manager import is_temp_or_locked_file
from ml.llm_classifier import classify_file_importance
from utils import user_data_paths
from utils.file_hash import calculate_file_hash

CONFIG_PATH = "config/config.json"
DEFAULT_CONFIG_PATH = CONFIG_PATH
DATASET_PATH = "dataset/files_dataset.csv"
ACTIVITY_PATH = "config/file_activity.json"

IMPORTANT_KEYWORDS = [
    "tcc",
    "projeto",
    "contrato",
    "relatorio",
    "financeiro",
    "documento",
]

CLASSIFICATION_FIELDS = [
    "priority",
    "priority_score",
    "priority_reason",
    "classification_source",
    "llm_confidence",
    "llm_model",
    "llm_error",
    "backup_policy",
    "decision_tree",
    "important",
]

# Estado compartilhado da classificacao em segundo plano.
# O scanner atualiza; a GUI le para exibir a barra de progresso.
CLASSIFICATION_STATUS = {
    "running": False,
    "total": 0,
    "done": 0,
    "status": "",
}
_CLASSIFICATION_STATUS_LOCK = threading.Lock()
_CLASSIFICATION_RUN_LOCK = threading.Lock()
_BACKGROUND_CLASSIFICATION_THREADS = set()
_BACKGROUND_CLASSIFICATION_THREADS_LOCK = threading.Lock()


def _update_classification_status(**kwargs):
    """Atualiza o CLASSIFICATION_STATUS de forma atomica (thread-safe)."""
    with _CLASSIFICATION_STATUS_LOCK:
        CLASSIFICATION_STATUS.update(**kwargs)


def get_classification_status():
    """Retorna uma copia do CLASSIFICATION_STATUS (thread-safe)."""
    with _CLASSIFICATION_STATUS_LOCK:
        return dict(CLASSIFICATION_STATUS)


def is_backup_execution_running():
    try:
        from backup.backup_manager import is_backup_job_running

        return is_backup_job_running()
    except Exception:
        return False


def wait_while_backup_execution_running():
    paused = False

    while is_backup_execution_running() and not is_shutdown_requested():
        paused = True
        _update_classification_status(
            running=True,
            status="Classificacao pausada: backup em andamento."
        )
        time.sleep(0.5)

    return paused


# Evento global de shutdown: quando setado, scanners e classificadores
# em segundo plano devem parar o mais rapido possivel.
_SHUTDOWN_EVENT = None


def set_shutdown_event(event):
    """Registra o evento de shutdown para ser verificado pelas threads."""
    global _SHUTDOWN_EVENT
    _SHUTDOWN_EVENT = event


def is_shutdown_requested():
    """Retorna True se o shutdown foi solicitado."""
    return _SHUTDOWN_EVENT is not None and _SHUTDOWN_EVENT.is_set()


def wait_for_shutdown(timeout):
    """Aguarda pelo shutdown sem deixar a thread presa em sleep fixo."""
    if _SHUTDOWN_EVENT is None:
        time.sleep(timeout)
        return False

    return _SHUTDOWN_EVENT.wait(timeout)


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
    if os.path.abspath(CONFIG_PATH) != os.path.abspath(DEFAULT_CONFIG_PATH):
        return load_json(CONFIG_PATH, {})

    scoped_path = user_data_paths.get_current_user_file_path("config.json")
    return load_json(scoped_path or CONFIG_PATH, {})


def load_directories(config=None):
    config = config or load_config()
    directories = config.get("directories", [])

    if not isinstance(directories, list):
        return []

    return [
        directory
        for directory in directories
        if isinstance(directory, str) and directory.strip()
    ]


def load_file_activity():
    return load_json(ACTIVITY_PATH, {})


def save_file_activity(activity_state):
    save_json(ACTIVITY_PATH, activity_state)


def contains_important_keyword(filename):
    name = filename.lower()

    for word in IMPORTANT_KEYWORDS:
        if word in name:
            return 1

    return 0


def get_file_type(extension):
    docs = ["doc", "docx", "pdf", "txt", "odt", "rtf"]
    code = ["py", "js", "ts", "java", "cpp", "c", "cs", "php"]
    images = ["jpg", "png", "jpeg", "gif", "webp"]
    sheets = ["xls", "xlsx", "ods", "csv"]
    databases = ["db", "sqlite", "sqlite3", "sql"]

    if extension in docs:
        return "document"

    if extension in code:
        return "code"

    if extension in images:
        return "image"

    if extension in sheets:
        return "spreadsheet"

    if extension in databases:
        return "database"

    return "other"


def ensure_not_cancelled(should_cancel=None):
    if is_shutdown_requested():
        raise BackupCancelledError("Sistema encerrado pelo usuario.")
    if should_cancel and should_cancel():
        raise BackupCancelledError("Backup cancelado pelo usuario.")


def normalize_activity_key(path):
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def format_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def update_file_activity(path, observed_stat, activity_state, scan_started_at, stored_stat=None):
    stored_stat = stored_stat or observed_stat
    key = normalize_activity_key(path)
    previous = activity_state.get(key, {})
    modified_count = safe_int(previous.get("modified_count"))
    accessed_count = safe_int(previous.get("accessed_count"))
    previous_mtime = previous.get("mtime")
    previous_atime = previous.get("atime")

    if previous:
        if previous_mtime is not None and abs(safe_float(previous_mtime) - observed_stat.st_mtime) > 0.001:
            modified_count += 1

        if previous_atime is not None and abs(safe_float(previous_atime) - observed_stat.st_atime) > 0.001:
            accessed_count += 1

    activity_state[key] = {
        "path": os.path.abspath(path),
        "mtime": stored_stat.st_mtime,
        "atime": stored_stat.st_atime,
        "modified_count": modified_count,
        "accessed_count": accessed_count,
        "first_seen_at": previous.get("first_seen_at") or scan_started_at,
        "last_seen_at": scan_started_at,
    }

    return activity_state[key]


def build_directory_context(file_path):
    directory = os.path.dirname(os.path.abspath(file_path))
    parts = []
    current = directory

    for _ in range(5):
        name = os.path.basename(current)

        if not name:
            break

        parts.insert(0, name)
        parent = os.path.dirname(current)

        if parent == current:
            break

        current = parent

    return " > ".join(parts)


def build_archive_name(directory, file_path):
    normalized_directory = os.path.abspath(os.path.normpath(directory))
    base_name = os.path.basename(normalized_directory.rstrip("\\/")) or "diretorio"
    relative_path = os.path.relpath(file_path, normalized_directory)
    return os.path.join(base_name, relative_path).replace("\\", "/")


def annotate_duplicates(files):
    seen_hashes = set()

    for file_data in files:
        file_hash = file_data.get("file_hash")

        if not file_hash:
            file_data["is_duplicate"] = 0
            file_data["duplicate_group"] = ""
            continue

        file_data["is_duplicate"] = 1 if file_hash in seen_hashes else 0
        file_data["duplicate_group"] = file_hash
        seen_hashes.add(file_hash)

    return files


def apply_classification(files, config=None, should_cancel=None, progress_callback=None):
    total_files = len(files)
    if total_files == 0:
        _update_classification_status(running=False, total=0, done=0, status="")
        return files

    _update_classification_status(
        running=True, total=total_files, done=0,
        status=f"Classificando {total_files} arquivo(s)..."
    )

    # Define o numero de workers: no maximo 8, no minimo 2, mas nunca
    # maior que a quantidade de arquivos para evitar threads ociosas.
    max_workers = min(max(2, os.cpu_count() or 4), 8, total_files)
    classified = 0
    lock = threading.Lock()

    def _update_status(done, total):
        _update_classification_status(
            done=done, total=total,
            status=f"Classificando {done}/{total} arquivos..."
        )

    def process_file(file_data):
        """Classifica um unico arquivo (thread-safe)."""
        ensure_not_cancelled(should_cancel)
        wait_while_backup_execution_running()
        ensure_not_cancelled(should_cancel)
        classification = classify_file_importance(file_data, config=config)

        for field in CLASSIFICATION_FIELDS:
            value = classification.get(field, "")
            if field in {"priority_reason", "llm_error"}:
                value = str(value)[:500]
            file_data[field] = value

        return file_data

    executor = None
    try:
        executor = ThreadPoolExecutor(max_workers=max_workers)
        futures = {executor.submit(process_file, f): f for f in files}

        for future in as_completed(futures):
            ensure_not_cancelled(should_cancel)

            with lock:
                classified += 1
                _update_status(classified, total_files)

            if progress_callback and (classified == total_files or classified % 10 == 0):
                percent = 30 + int((classified / max(total_files, 1)) * 5)
                progress_callback(
                    min(percent, 35),
                    f"Classificando arquivos {classified}/{total_files}"
                )
    except (KeyboardInterrupt, SystemExit):
        _update_classification_status(
            running=False, done=classified, total=total_files,
            status=f"Classificacao interrompida: {classified}/{total_files}."
        )
        return files
    except BackupCancelledError:
        # Shutdown solicitado: nao bloqueia aguardando tarefas em execucao
        _update_classification_status(
            running=False, done=classified, total=total_files,
            status=f"Classificacao interrompida: {classified}/{total_files}."
        )
        return files
    finally:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    _update_classification_status(
        running=False, done=total_files, total=total_files,
        status=f"Classificacao concluida: {total_files} arquivos."
    )
    return files


def mark_classification_pending(files):
    for file_data in files:
        for field in CLASSIFICATION_FIELDS:
            file_data[field] = ""

        file_data["classification_source"] = "pending_background"
        file_data["important"] = 0

    return files


def scan_directory(
    directory,
    should_cancel=None,
    added_to_backup_at=None,
    activity_state=None,
    scan_started_at=None
):
    results = []
    normalized_directory = os.path.normpath(directory)
    activity_state = activity_state if activity_state is not None else {}
    scan_started_at = scan_started_at or datetime.now().isoformat(timespec="seconds")

    if not os.path.isdir(normalized_directory):
        return results

    if is_path_ignored(normalized_directory):
        return results

    def _walk_error(os_error):
        """Ignora diretorios sem permissao de leitura."""
        print(f"Aviso: sem acesso a {os_error.filename} - ignorando.")

    for root, dirs, files in os.walk(normalized_directory, onerror=_walk_error):
        ensure_not_cancelled(should_cancel)

        dirs[:] = [
            current_dir
            for current_dir in dirs
            if not is_path_ignored(os.path.join(root, current_dir))
        ]

        for file in files:
            ensure_not_cancelled(should_cancel)

            if is_temp_or_locked_file(file):
                continue

            try:
                path = os.path.join(root, file)

                if is_path_ignored(path):
                    continue

                stat = os.stat(path)
                size_kb = stat.st_size / 1024
                modified_time = stat.st_mtime
                accessed_time = stat.st_atime
                days_since_modified = (
                    datetime.now() - datetime.fromtimestamp(modified_time)
                ).days
                days_since_accessed = (
                    datetime.now() - datetime.fromtimestamp(accessed_time)
                ).days
                extension = os.path.splitext(file)[1].lstrip(".").lower()
                file_type = get_file_type(extension)
                important_keyword = contains_important_keyword(file)
                file_hash = calculate_file_hash(path)
                stored_stat = os.stat(path)
                activity = update_file_activity(
                    path,
                    stat,
                    activity_state,
                    scan_started_at,
                    stored_stat=stored_stat
                )

                results.append(
                    {
                        "name": file,
                        "extension": extension,
                        "type": file_type,
                        "source_path": os.path.abspath(path),
                        "archive_name": build_archive_name(normalized_directory, path),
                        "directory_context": build_directory_context(path),
                        "size_kb": size_kb,
                        "days_since_modified": days_since_modified,
                        "days_since_accessed": days_since_accessed,
                        "last_modified_at": format_timestamp(modified_time),
                        "last_accessed_at": format_timestamp(accessed_time),
                        "modified_count": activity.get("modified_count", 0),
                        "accessed_count": activity.get("accessed_count", 0),
                        "added_to_backup_at": added_to_backup_at or "",
                        "file_hash": file_hash,
                        "important_keyword": important_keyword,
                        "important": 0,
                    }
                )

            except Exception as error:
                print("[AVISO] Erro ao ler arquivo:", file, error)

    return results


def run_scanner(should_cancel=None, progress_callback=None, classify_files=True):
    print("\nIniciando scanner...\n")

    config = load_config()
    directories = load_directories(config)
    added_to_backup_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    scan_started_at = datetime.now().isoformat(timespec="seconds")
    activity_state = load_file_activity()

    if not directories:
        print("Nenhum diretorio configurado.")
        return

    all_files = []
    total_directories = len(directories)

    for index, directory in enumerate(directories, start=1):
        ensure_not_cancelled(should_cancel)

        print("Escaneando:", directory)

        if progress_callback:
            percent = 5 + int((index - 1) / max(total_directories, 1) * 25)
            progress_callback(percent, f"Escaneando diretorio {index}/{total_directories}")

        files = scan_directory(
            directory,
            should_cancel=should_cancel,
            added_to_backup_at=added_to_backup_at,
            activity_state=activity_state,
            scan_started_at=scan_started_at,
        )

        all_files.extend(files)

    ensure_not_cancelled(should_cancel)
    save_file_activity(activity_state)

    if not all_files:
        print("Nenhum arquivo encontrado.")
        return

    annotate_duplicates(all_files)

    if classify_files:
        apply_classification(
            all_files,
            config=config,
            should_cancel=should_cancel,
            progress_callback=progress_callback,
        )
    else:
        mark_classification_pending(all_files)

    df = pd.DataFrame(all_files)

    os.makedirs("dataset", exist_ok=True)
    df.to_csv(DATASET_PATH, index=False)

    print("\nDataset atualizado:", DATASET_PATH)
    print("Arquivos analisados:", len(df))

    if progress_callback:
        progress_callback(35, f"Scanner concluiu {len(df)} arquivo(s).")


def run_classification_background(config=None):
    """Re-classifica o dataset atual em segundo plano (thread separada).

    Le o CSV ja salvo pelo scanner. Arquivos que ja possuem classificacao
    valida (mesmo file_hash) no dataset anterior sao reaproveitados —
    apenas arquivos novos ou modificados sao classificados.

    Usa um lock para garantir que apenas uma classificacao rode por vez —
    se outra for solicitada enquanto uma ja estiver em andamento, ela e
    ignorada silenciosamente.
    """
    if not _CLASSIFICATION_RUN_LOCK.acquire(blocking=False):
        # Ja existe uma classificacao rodando, ignora esta solicitacao
        return None

    PREVIOUS_DATASET_PATH = DATASET_PATH.replace(".csv", "_previous.csv")

    def _load_previous_index():
        """Carrega o dataset anterior e indexa por file_hash para reuso."""
        if not os.path.exists(PREVIOUS_DATASET_PATH):
            return {}
        try:
            prev_df = pd.read_csv(PREVIOUS_DATASET_PATH)
            index = {}
            for _, row in prev_df.iterrows():
                fhash = str(row.get("file_hash", "")).strip()
                if fhash and str(row.get("priority", "")).strip():
                    index[fhash] = row.to_dict()
            return index
        except Exception:
            return {}

    def _classify_worker():
        try:
            if not os.path.exists(DATASET_PATH):
                return

            df = pd.read_csv(DATASET_PATH)
            if df.empty:
                return

            records = df.to_dict(orient="records")
            _config = config or load_config()

            # Indexa classificacoes anteriores por hash
            previous_index = _load_previous_index()
            pending = []
            reused = 0

            for rec in records:
                fhash = str(rec.get("file_hash", "")).strip()
                prev = previous_index.get(fhash)

                if prev and str(prev.get("priority", "")).strip():
                    # Reaproveita classificacao anterior
                    for field in CLASSIFICATION_FIELDS:
                        rec[field] = prev.get(field, "")
                    reused += 1
                else:
                    # Arquivo novo ou modificado: precisa classificar
                    pending.append(rec)

            if pending:
                if is_shutdown_requested():
                    print("Classificacao em segundo plano cancelada (shutdown).")
                    return

                if wait_while_backup_execution_running():
                    print("Classificacao em segundo plano retomada apos backup.")

                print(
                    f"Classificacao em segundo plano: "
                    f"{len(pending)} pendente(s), {reused} reaproveitado(s)..."
                )
                apply_classification(
                    pending, config=_config,
                    should_cancel=is_shutdown_requested
                )
            else:
                print(
                    f"Classificacao em segundo plano: "
                    f"todos os {reused} arquivos ja estao classificados."
                )
                _update_classification_status(
                    running=False, total=reused, done=reused,
                    status=f"Classificacao concluida: {reused} arquivos."
                )

            # Salva o dataset atualizado
            pd.DataFrame(records).to_csv(DATASET_PATH, index=False)

            # Salva copia com classificacoes para reuso na proxima execucao
            try:
                pd.DataFrame(records).to_csv(PREVIOUS_DATASET_PATH, index=False)
            except Exception:
                pass

            if pending:
                print("Classificacao em segundo plano concluida.")
        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception as error:
            print(f"Erro na classificacao em segundo plano: {error}")
        finally:
            _CLASSIFICATION_RUN_LOCK.release()
            with _BACKGROUND_CLASSIFICATION_THREADS_LOCK:
                _BACKGROUND_CLASSIFICATION_THREADS.discard(threading.current_thread())

    thread = threading.Thread(target=_classify_worker, daemon=True, name="bg-classifier")
    with _BACKGROUND_CLASSIFICATION_THREADS_LOCK:
        _BACKGROUND_CLASSIFICATION_THREADS.add(thread)
    thread.start()
    return thread


def wait_for_background_classification_threads(timeout=5.0):
    with _BACKGROUND_CLASSIFICATION_THREADS_LOCK:
        threads = list(_BACKGROUND_CLASSIFICATION_THREADS)

    for thread in threads:
        if thread is threading.current_thread():
            continue

        if thread.is_alive():
            thread.join(timeout=timeout)


if __name__ == "__main__":
    run_scanner()
