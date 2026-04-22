import hashlib


def calculate_file_hash(path, chunk_size=65536):
    hasher = hashlib.sha256()

    with open(path, "rb") as file:
        while chunk := file.read(chunk_size):
            hasher.update(chunk)

    return hasher.hexdigest()
