import os
import json
from pathlib import Path
from datetime import datetime
import pandas as pd

CONFIG_FILE = "config/config.json"


IMPORTANT_KEYWORDS = [
    "tcc",
    "contrato",
    "documento",
    "projeto",
    "financeiro",
    "relatorio"
]


DOCUMENT_TYPES = {
    ".doc": "document",
    ".docx": "document",
    ".pdf": "document",
    ".txt": "document",
    ".xls": "spreadsheet",
    ".xlsx": "spreadsheet",
    ".ppt": "presentation",
    ".pptx": "presentation",
    ".jpg": "image",
    ".png": "image",
    ".mp4": "video",
    ".zip": "archive",
    ".py": "code",
    ".js": "code",
    ".java": "code"
}


def detect_file_type(extension):

    return DOCUMENT_TYPES.get(extension.lower(), "other")


def contains_keyword(filename):

    name = filename.lower()

    for word in IMPORTANT_KEYWORDS:
        if word in name:
            return 1

    return 0


def load_directories():

    if not os.path.exists(CONFIG_FILE):
        return []

    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            return data.get("directories", [])

    except Exception:
        return []


def scan_directory(directory):

    results = []

    now = datetime.now()

    for root, dirs, files in os.walk(directory):

        for file in files:

            filepath = os.path.join(root, file)

            try:

                stat = os.stat(filepath)

                ext = Path(file).suffix.lower()

                created = datetime.fromtimestamp(stat.st_ctime)
                modified = datetime.fromtimestamp(stat.st_mtime)

                data = {

                    "name": file,
                    "path": filepath,
                    "extension": ext,
                    "type": detect_file_type(ext),

                    "size_kb": stat.st_size / 1024,

                    "days_since_created":
                        (now - created).days,

                    "days_since_modified":
                        (now - modified).days,

                    "important_keyword":
                        contains_keyword(file)
                }

                results.append(data)

            except Exception as e:

                print("Erro ao ler:", filepath, e)

    return results


def run_scanner():

    directories = load_directories()

    all_files = []

    for directory in directories:

        print("Escaneando:", directory)

        files = scan_directory(directory)

        all_files.extend(files)

    df = pd.DataFrame(all_files)

    os.makedirs("dataset", exist_ok=True)

    df.to_csv("dataset/files_dataset.csv", index=False)

    print("Scan finalizado!")