import json, csv
from pathlib import Path
from collections import Counter

# Snapshot
base = Path(r"C:\Users\super\Downloads\TCC\sistema-backup-inteligente\backups\diogo_gmail.com")
snapshots = sorted(base.rglob("snapshot_*.json"))
if snapshots:
    s = snapshots[-1]
    d = json.loads(s.read_text(encoding="utf-8"))
    print(f"Snapshot: {s.name}")
    print(f"Total files: {d.get('total_files', '?')}")
    print(f"Created: {d.get('created_at', '?')}")
    sc = d.get("status_counts", {})
    print(f"Status: {json.dumps(sc)}")
    pc = Counter()
    for f in d.get("files", []):
        pc[f.get("priority", "?")] += 1
    print(f"Prioridades no snapshot: {dict(pc)}")

# Dataset
prio = Counter(); src = Counter(); err = Counter()
with open(r"C:\Users\super\Downloads\TCC\sistema-backup-inteligente\dataset\files_dataset.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        prio[row.get("priority", "?")] += 1
        src[row.get("classification_source", "?")] += 1
        e = row.get("llm_error", "").strip()
        if "429" in e: err["HTTP 429"] += 1
        elif "503" in e: err["HTTP 503"] += 1
        elif "timeout" in e.lower() or "timed out" in e.lower(): err["Timeout"] += 1
        elif e: err["Outro"] += 1

total = sum(prio.values())
print(f"\nDataset: {total} arquivos")
print(f"Prioridade: {dict(prio)}")
print(f"Fonte: {dict(src)}")
print(f"Erros Gemini: {dict(err)} (total={sum(err.values())})")
