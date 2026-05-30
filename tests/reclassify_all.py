"""Dedup e reclassifica o dataset com rate limiting + batch."""
import csv, json, sys, time
sys.path.insert(0, ".")

# 1. Dedup dataset
hashes = set()
unique = []
with open("dataset/files_dataset.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fn = reader.fieldnames
    for row in reader:
        h = row.get("file_hash", "") or row.get("hash", "")
        if h and h not in hashes:
            hashes.add(h)
            unique.append(row)

print(f"Original: {sum(1 for _ in open('dataset/files_dataset.csv'))-1} linhas")
print(f"Dedup: {len(unique)} linhas unicas")

# Salva dedup
with open("dataset/files_dataset.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fn)
    w.writeheader()
    w.writerows(unique)
print("Dataset dedup salvo.")

# 2. Reclassifica com batch
from ml.llm_classifier import classify_files_batch

print(f"\nReclassificando {len(unique)} arquivos com batch...")
t0 = time.monotonic()
results = classify_files_batch(unique)
t1 = time.monotonic()

# 3. Atualiza dataset com novos resultados
for i, row in enumerate(unique):
    if i < len(results):
        r = results[i]
        row["priority"] = r.get("priority", "baixa")
        row["priority_score"] = str(r.get("priority_score", 0))
        row["priority_reason"] = "; ".join(r.get("reasons", []))
        row["classification_source"] = r.get("classification_source", "rules")
        row["llm_confidence"] = str(r.get("confidence", ""))
        row["llm_model"] = r.get("llm_model", "")
        row["llm_error"] = r.get("llm_error", "")
        row["important"] = "1" if r.get("priority") in ("alta", "media") else "0"

with open("dataset/files_dataset.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fn)
    w.writeheader()
    w.writerows(unique)

# 4. Report
from collections import Counter
prio = Counter()
src = Counter()
for r in results:
    prio[r.get("priority", "?")] += 1
    src[r.get("classification_source", "?")] += 1

print(f"\nTempo total: {t1-t0:.0f}s ({t1-t0:.1f}s)")
print(f"Prioridades: {dict(prio)}")
print(f"Fontes: {dict(src)}")
print(f"Dataset atualizado!")
