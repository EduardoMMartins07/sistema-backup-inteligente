import os
import json
import pandas as pd
from datetime import datetime

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


def scan_directory(directory):

    results = []

    for root, dirs, files in os.walk(directory):

        for file in files:

            try:

                path = os.path.join(root, file)

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


def run_scanner():

    print("\nIniciando scanner...\n")

    directories = load_directories()

    if not directories:
        print("Nenhum diretório configurado.")
        return

    all_files = []

    for d in directories:

        print("Escaneando:", d)

        files = scan_directory(d)

        all_files.extend(files)

    if not all_files:
        print("Nenhum arquivo encontrado.")
        return

    df = pd.DataFrame(all_files)

    os.makedirs("dataset", exist_ok=True)

    df.to_csv(DATASET_PATH, index=False)

    print("\nDataset atualizado:", DATASET_PATH)
    print("Arquivos analisados:", len(df))


# execução direta para teste
if __name__ == "__main__":

    run_scanner()