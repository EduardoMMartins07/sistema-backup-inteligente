"""Extrai métricas do backup diogo@gmail.com para o artigo."""
import json
from pathlib import Path

base = Path(r"C:\Users\super\Downloads\TCC\sistema-backup-inteligente\backups\diogo_gmail.com")

print("=== Diretórios de objetos ===")
for d in sorted(base.rglob("*")):
    if d.is_dir():
        files = [f for f in d.iterdir() if f.is_file()]
        if files:
            total = sum(f.stat().st_size for f in files)
            print(f"  {d.relative_to(base)}: {len(files)} arquivos, {total/1024:.0f} KB ({total/(1024**2):.1f} MB)")

print()
print("=== Snapshots ===")
snapshots = sorted(base.rglob("snapshot_*.json"))
for s in snapshots:
    data = json.loads(s.read_text(encoding="utf-8"))
    print(f"\n{s.name}:")
    for key in ["total_files", "objects_stored", "objects_referenced",
                 "files_unchanged", "files_not_eligible", "duplicate_files_skipped",
                 "compacted_size_bytes", "trigger", "cloud_sync_status", "encrypted"]:
        print(f"  {key}: {data.get(key)}")

# Total storage
total_storage = sum(
    f.stat().st_size for f in base.rglob("*")
    if f.is_file() and "snapshot" not in f.name
)
print(f"\n=== Total armazenado (objetos): {total_storage:,} bytes ({total_storage/(1024**2):.1f} MB) ===")

# Custo S3
gb = total_storage / (1024**3)
print(f"\n=== Estimativa de Custo S3 (Standard, us-east-1) ===")
print(f"  Volume: {gb:.4f} GB")
print(f"  Armazenamento: ${gb * 0.023:.4f}/mês")
print(f"  Transferência OUT (1x): ${gb * 0.09:.4f}")
print(f"  PUT requests (~{max(1, total_storage // (8*1024*1024))}): ${max(1, total_storage // (8*1024*1024)) * 0.005 / 1000:.6f}")
print(f"  TOTAL mensal estimado: ${gb * 0.023 + gb * 0.09:.4f}")
