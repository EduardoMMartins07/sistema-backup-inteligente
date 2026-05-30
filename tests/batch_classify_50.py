"""Classifica em lotes de 50 (dentro da cota gratuita de tokens/min)."""
import json, csv, sys, time
from collections import Counter
sys.path.insert(0, ".")
import ml.llm_classifier as llm

# Forca batch size pequeno para caber na cota gratuita (4K TPM)
llm.GEMINI_BATCH_SIZE = 50
llm.GEMINI_RPM_LIMIT = 15

rows = []
with open("dataset/files_dataset.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        rows.append(row)

print(f"Classificando {len(rows)} arquivos em lotes de {llm.GEMINI_BATCH_SIZE}...")
t0 = time.monotonic()
results = llm.classify_files_batch(rows)
t1 = time.monotonic()

# Atualiza dataset
fn = list(rows[0].keys()) if rows else []
for i, row in enumerate(rows):
    if i < len(results):
        r = results[i]
        row["priority"] = r.get("priority", "baixa")
        row["priority_score"] = str(r.get("priority_score", 0))
        row["priority_reason"] = "; ".join(r.get("reasons", []))
        row["classification_source"] = r.get("classification_source", "rules")
        row["llm_confidence"] = str(r.get("confidence", ""))
        row["llm_model"] = r.get("llm_model", "")
        row["llm_error"] = r.get("llm_error", "")

with open("dataset/files_dataset.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fn)
    w.writeheader()
    w.writerows(rows)

prio = Counter(); src = Counter()
for r in results:
    prio[r.get("priority", "?")] += 1
    src[r.get("classification_source", "?")] += 1
print(f"\nTempo: {t1-t0:.0f}s")
print(f"Prioridades: {dict(prio)}")
print(f"Fontes: {dict(src)}")
errors = sum(1 for r in results if r.get("classification_source") == "rules_fallback" and r.get("llm_error"))
sucesso_api = src.get("gemini_api", 0) + src.get("gemini_cache", 0)
print(f"Sucesso Gemini: {sucesso_api} / {len(results)} ({100*sucesso_api/len(results):.1f}%)")
print(f"Fallbacks com erro: {errors}")
