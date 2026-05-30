"""Classifica TODOS os 4048 arquivos em lotes otimizados (60 arq/batch ~3K tokens)."""
import json, csv, sys, time
from collections import Counter
sys.path.insert(0, ".")
import ml.llm_classifier as llm

# Le dataset
rows = []
with open("dataset/files_dataset.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        rows.append(row)

BATCH = 60  # ~3K tokens/lote, dentro dos 4K TPM gratuitos
total = len(rows)
print(f"Classificando {total} arquivos em {total//BATCH + 1} lotes...")
t0 = time.monotonic()

all_results = []
for i in range(0, total, BATCH):
    batch = rows[i:i+BATCH]
    res = llm.classify_all_in_one(batch)
    all_results.extend(res)
    n = min(i+BATCH, total)
    gem = sum(1 for r in res if r.get("classification_source") == "gemini_api")
    print(f"  Lote {i//BATCH + 1}: {n}/{total} ({gem} gemini)")

t1 = time.monotonic()

# Atualiza dataset
fn = list(rows[0].keys()) if rows else []
for i, row in enumerate(rows):
    if i < len(all_results):
        r = all_results[i]
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
    w.writerows(rows)

prio = Counter(); src = Counter(); err_c = Counter()
for r in all_results:
    prio[r.get("priority", "?")] += 1
    src[r.get("classification_source", "?")] += 1
    if r.get("classification_source") == "rules_fallback":
        e = r.get("llm_error", "")[:50]
        err_c[e] += 1

print(f"\nTempo: {(t1-t0)/60:.1f} min")
print(f"Prioridades: alta={prio.get('alta',0)}, media={prio.get('media',0)}, baixa={prio.get('baixa',0)}")
print(f"Fontes: {dict(src)}")
print(f"Fallbacks: {sum(err_c.values())}")
if err_c:
    print(f"Erros: {err_c.most_common(3)}")
