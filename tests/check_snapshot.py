import json
d = json.loads(open(r"C:\Users\super\Downloads\TCC\sistema-backup-inteligente\backups\diogo_gmail.com\2026-05-30\snapshots\snapshot_2026-05-30_18-12-37.json", encoding="utf-8").read())

print("Top-level keys:", list(d.keys()))
sc = d.get("status_counts", {})
print("Status counts:", json.dumps(sc, indent=2))

files = d.get("files", [])
print(f"\nType of 'files': {type(files).__name__}, length: {len(files)}")

# Amostra de 5
for i, item in enumerate(files[:5]):
    print(f"  {item}")

# Verifica se algum arquivo tem status 'excluded' ou 'skipped'
from collections import Counter
status_counter = Counter()
for f in files:
    if isinstance(f, dict):
        status_counter[f.get("status", "?")] += 1

print(f"\nStatus distribution: {dict(status_counter)}")
print(f"Total: {sum(status_counter.values())}")

