"""Classifica TODOS os 4048 arquivos com DeepSeek (lotes de 50)."""
import csv, sys, time
from collections import Counter
sys.path.insert(0, ".")
import ml.llm_classifier as llm

rows = []
with open("dataset/files_dataset.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        rows.append(row)

BATCH = 50
total = len(rows)
print(f"Classificando {total} arquivos em lotes de {BATCH}...\n")
t0 = time.monotonic()

all_results = []
for i in range(0, total, BATCH):
    batch = rows[i:i+BATCH]
    res = llm.classify_all_in_one(batch)
    all_results.extend(res)
    n = min(i+BATCH, total)
    gem = sum(1 for r in res if r.get("classification_source") in ("gemini_api", "gemini_cache"))
    fall = sum(1 for r in res if r.get("classification_source") == "rules_fallback")
    print(f"  Lote {i//BATCH+1:2d}: {n:4d}/{total} ({100*n/total:.0f}%) -- gemini={gem} fallback={fall}")

    # Salva progressivamente a cada 10 lotes
    if (i // BATCH + 1) % 10 == 0:
        for idx, row in enumerate(rows):
            if idx < len(all_results):
                r = all_results[idx]
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
        print(f"         [salvo parcial: {len(all_results)}/{total}]")

t1 = time.monotonic()

# Atualiza dataset
fn = list(all_results[0].keys()) if all_results else []
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
        e = r.get("llm_error", "")[:60]
        err_c[e] += 1

print(f"\nTempo: {(t1-t0)/60:.1f} min")
print(f"Prioridades: alta={prio.get('alta',0)} media={prio.get('media',0)} baixa={prio.get('baixa',0)}")
print(f"Fontes: {dict(src)}")
print(f"Total gemini/deepseek: {src.get('gemini_api',0)+src.get('gemini_cache',0)}/{total}")
print(f"Erros fallback: {sum(err_c.values())}")
if err_c:
    print(f"  {err_c.most_common(3)}")
