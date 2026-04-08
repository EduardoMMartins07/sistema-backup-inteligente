import os
import json
import pandas as pd
from datetime import datetime

from backup.backup_manager import BackupCancelledError
from backup.backup_manager import is_path_ignored

CONFIG_PATH = "config/config.json"
DATASET_PATH = "dataset/files_dataset.csv"

# palavras que indicam arquivos importantes
IMPORTANT_KEYWORDS = [
    "tcc",
    "projeto",
    "contrato",
    "relatorio",
    "financeiro",
    "documento"
]


def load_directories():

    if not os.path.exists(CONFIG_PATH):
        print("config.json não encontrado")
        return []

    with open(CONFIG_PATH, "r") as f:

        try:
            data = json.load(f)
        except:
            return []

    return data.get("directories", [])


def contains_important_keyword(filename):

    name = filename.lower()

    for word in IMPORTANT_KEYWORDS:
        if word in name:
            return 1

    return 0


def get_file_type(extension):

    docs = ["doc", "docx", "pdf", "txt"]
    code = ["py", "js", "java", "cpp"]
    images = ["jpg", "png", "jpeg"]

    if extension in docs:
        return "document"

    if extension in code:
        return "code"

    if extension in images:
        return "image"

    return "other"


def ensure_not_cancelled(should_cancel=None):
    if should_cancel and should_cancel():
        raise BackupCancelledError("Backup cancelado pelo usuario.")


def scan_directory(directory, should_cancel=None):

    results = []
    normalized_directory = os.path.normpath(directory)

    if not os.path.isdir(normalized_directory):
        return results

    if is_path_ignored(normalized_directory):
        return results

    for root, dirs, files in os.walk(normalized_directory):
        ensure_not_cancelled(should_cancel)

        dirs[:] = [
            current_dir
            for current_dir in dirs
            if not is_path_ignored(os.path.join(root, current_dir))
        ]

        for file in files:
            ensure_not_cancelled(should_cancel)

            try:

                path = os.path.join(root, file)

                if is_path_ignored(path):
                    continue

                size_kb = os.path.getsize(path) / 1024

                modified_time = os.path.getmtime(path)

                days_since_modified = (
                    datetime.now() - datetime.fromtimestamp(modified_time)
                ).days

                extension = file.split(".")[-1].lower()

                file_type = get_file_type(extension)

                important_keyword = contains_important_keyword(file)

                # heurística simples para gerar label
                important = 1 if important_keyword == 1 else 0

                results.append({

                    "name": file,
                    "extension": extension,
                    "type": file_type,
                    "size_kb": size_kb,
                    "days_since_modified": days_since_modified,
                    "important_keyword": important_keyword,
                    "important": important

                })

            except Exception as e:

                print("Erro ao ler arquivo:", file, e)

    return results


def run_scanner(should_cancel=None, progress_callback=None):

    print("\nIniciando scanner...\n")

    directories = load_directories()

    if not directories:
        print("Nenhum diretório configurado.")
        return

    all_files = []
    total_directories = len(directories)

    for index, d in enumerate(directories, start=1):
        ensure_not_cancelled(should_cancel)

        print("Escaneando:", d)

        if progress_callback:
            percent = 5 + int((index - 1) / max(total_directories, 1) * 25)
            progress_callback(percent, f"Escaneando diretorio {index}/{total_directories}")

        files = scan_directory(d, should_cancel=should_cancel)

        all_files.extend(files)

    ensure_not_cancelled(should_cancel)

    if not all_files:
        print("Nenhum arquivo encontrado.")
        return

    df = pd.DataFrame(all_files)

    os.makedirs("dataset", exist_ok=True)

    df.to_csv(DATASET_PATH, index=False)

    print("\nDataset atualizado:", DATASET_PATH)
    print("Arquivos analisados:", len(df))

    if progress_callback:
        progress_callback(35, f"Scanner concluiu {len(df)} arquivo(s).")


# execução direta para teste
if __name__ == "__main__":

    run_scanner()
