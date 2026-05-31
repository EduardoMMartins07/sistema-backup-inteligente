import csv
from collections import Counter
src = Counter(); prio = Counter()
with open("dataset/files_dataset.csv") as f:
    for r in csv.DictReader(f):
        src[r["classification_source"]] += 1
        prio[r["priority"]] += 1
total = sum(prio.values())
print(f"Total: {total}")
print(f"Fontes: {dict(src)}")
print(f"Prioridades: alta={prio.get('alta',0)} media={prio.get('media',0)} baixa={prio.get('baixa',0)}")
gem = src.get("gemini_api", 0) + src.get("gemini_cache", 0)
print(f"Gemini/DeepSeek: {gem}/{total} ({100*gem/total:.0f}%)")
