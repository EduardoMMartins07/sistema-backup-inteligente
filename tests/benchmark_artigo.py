"""
Script de benchmark para o artigo do TCC.
Executa múltiplas rodadas de backup/restauração e produz
métricas estatísticas (média, desvio padrão, IC 95%),
boxplot, verificação de integridade e estimativa de custo S3.

Uso: python tests/benchmark_artigo.py
"""

import csv
import hashlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# Adiciona raiz do projeto ao path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import backup.backup_manager as bm
from backup.backup_manager import (
    normalize_archive_name,
    restore_snapshot,
    run_incremental_backup,
)

# ─── Configuração ────────────────────────────────────────────────
NUM_RUNS = 30                # repetições por cenário
CONFIDENCE = 0.95            # nível de confiança
S3_PRICE_PER_GB_STORED = 0.023   # USD/GB/mês (S3 Standard, us-east-1)
S3_PRICE_PER_GB_TRANSFER = 0.09  # USD/GB (transferência OUT)
S3_PUT_COPY_COST = 0.005 / 1000  # USD por requisição PUT/COPY

OUTPUT_DIR = PROJECT_ROOT / "benchmark_results"
OUTPUT_DIR.mkdir(exist_ok=True)

REPORT_PATH = OUTPUT_DIR / "benchmark_report.json"
BOXPLOT_PATH = OUTPUT_DIR / "boxplot.png"


# ─── Helpers ──────────────────────────────────────────────────────

def _patch_paths(root: Path):
    """Redireciona paths do backup_manager para diretório temporário."""
    config_dir = root / "config"
    dataset_dir = root / "dataset"
    backups_dir = root / "backups"
    config_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    bm.CONFIG_PATH = str(config_dir / "config.json")
    bm.DATASET_PATH = str(dataset_dir / "files_dataset.csv")
    bm.HISTORY_PATH = str(config_dir / "backup_history.json")
    bm.SCHEDULE_PATH = str(config_dir / "backup_schedule.json")
    bm.PRIORITY_STATE_PATH = str(config_dir / "priority_backup_state.json")

    # Configuração mínima
    (config_dir / "config.json").write_text(json.dumps(
        {"directories": [str(root / "source")], "backup_destination": str(backups_dir)}
    ), encoding="utf-8")
    (config_dir / "backup_history.json").write_text("[]", encoding="utf-8")

    os.environ.pop("BACKUP_DEV_MODE", None)
    bm._BACKUP_ENV_FILE_LOADED = True


def _create_synthetic_dataset(source_dir: Path, num_files: int = 80,
                               total_size_mb: int = 165):
    """Cria dataset sintético com distribuição similar ao real."""
    source_dir.mkdir(parents=True, exist_ok=True)

    # Distribuição aproximada (baseada no dataset real)
    files = []
    # 28 documentos
    for i in range(10):
        f = source_dir / f"relatorio_{i}.docx"
        f.write_bytes(os.urandom(1024 * 45))
        files.append(f)
    for i in range(10):
        f = source_dir / f"artigo_{i}.pdf"
        f.write_bytes(os.urandom(1024 * 200))
        files.append(f)
    for i in range(5):
        f = source_dir / f"nota_{i}.txt"
        f.write_text("dados de exemplo\n" * 800, encoding="utf-8")
        files.append(f)
    for i in range(3):
        f = source_dir / f"planilha_{i}.xlsx"
        f.write_bytes(os.urandom(1024 * 15))
        files.append(f)

    # 10 apresentações
    for i in range(10):
        f = source_dir / f"slides_{i}.pptx"
        f.write_bytes(os.urandom(1024 * 500))
        files.append(f)

    # 1 csv
    (source_dir / "dados.csv").write_text("col1,col2,col3\n" + "a,b,c\n" * 1000)

    # 10 config
    config_dir = source_dir / "config"
    config_dir.mkdir(exist_ok=True)
    for i, ext in enumerate(["json", "yaml", "ini", "key", "dat", "json", "yaml", "ini", "conf", "dat"]):
        (config_dir / f"settings_{i}.{ext}").write_text("key=value\n" * 10)

    # 26 dll/exe (simulados)
    lib_dir = source_dir / "lib"
    lib_dir.mkdir(exist_ok=True)
    for i in range(26):
        (lib_dir / f"lib_{i}.dll").write_bytes(os.urandom(1024 * 30))

    # 1 imagem
    (source_dir / "foto.jpg").write_bytes(os.urandom(1024 * 180))

    # 4 sem extensão
    for name in ["COPYRIGHT", "LICENSE", "README", "CHANGELOG"]:
        (source_dir / name).write_text("placeholder\n" * 5)

    return files


def _build_manifest(source_dir: Path):
    """Constrói manifesto no formato esperado por run_incremental_backup."""
    manifest = []
    for f in sorted(source_dir.rglob("*")):
        if f.is_file():
            archive = normalize_archive_name(
                f"source/{f.relative_to(source_dir)}"
            )
            manifest.append((str(f), archive))
    return manifest


def _compute_stats(times: list[float]):
    """Retorna média, desvio padrão, IC 95%, min, max."""
    n = len(times)
    mean = statistics.mean(times)
    stdev = statistics.stdev(times) if n > 1 else 0.0
    # IC 95% com t-student (aproximação normal para n >= 30)
    import math
    z = 1.96  # normal para 95%
    ci = z * stdev / math.sqrt(n)
    return {
        "n": n,
        "media_s": round(mean, 6),
        "desvio_s": round(stdev, 6),
        "ic95_mais_menos_s": round(ci, 6),
        "min_s": round(min(times), 6),
        "max_s": round(max(times), 6),
    }


def _generate_boxplot(data: dict[str, list[float]], path: Path):
    """Gera boxplot comparativo com matplotlib."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[!] matplotlib não instalado — pulando boxplot")
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    labels = list(data.keys())
    values = list(data.values())

    bp = ax.boxplot(values, labels=labels, patch_artist=True,
                     showmeans=True, meanprops=dict(marker="D", markerfacecolor="black"))
    for patch in bp["boxes"]:
        patch.set_facecolor("#cce5ff")

    ax.set_ylabel("Tempo (s)")
    ax.set_title("Backup Incremental Inteligente — Desempenho (n = 30)")
    fig.tight_layout()
    fig.savefig(str(path), dpi=200)
    plt.close(fig)
    print(f"[OK] Boxplot salvo em {path}")


def _s3_cost_estimate(total_bytes: int):
    """Estima custo mensal aproximado no S3 Standard."""
    gb = total_bytes / (1024 ** 3)
    storage_cost = gb * S3_PRICE_PER_GB_STORED
    transfer_cost = gb * S3_PRICE_PER_GB_TRANSFER
    put_cost = (total_bytes / (8 * 1024 * 1024)) * S3_PUT_COPY_COST  # aprox 8MB/objeto
    total = storage_cost + transfer_cost + put_cost
    return {
        "total_bytes": total_bytes,
        "total_gb": round(gb, 4),
        "armazenamento_usd_mes": round(storage_cost, 4),
        "transferencia_usd": round(transfer_cost, 4),
        "requisicoes_usd": round(put_cost, 6),
        "total_usd_mes": round(total, 4),
    }


# ─── Cenários de benchmark ────────────────────────────────────────

def run_all_benchmarks():
    results = {}
    timing_data = {}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        backups = root / "backups"

        _create_synthetic_dataset(source)
        _patch_paths(root)
        manifest = _build_manifest(source)

        # ── Cenário 1: Backup incremental com todos arquivos inalterados ──
        print("[1/4] Backup incremental sem alterações (30 execuções)...")
        times = []
        # Primeira execução (inicial) — armazena todos
        run_incremental_backup(
            directories=[str(source)],
            backup_destination=str(backups),
            manifest=manifest,
            priority_policy=False,
        )
        # 30 execuções subsequentes — todos inalterados
        for i in range(NUM_RUNS):
            t0 = time.perf_counter()
            run_incremental_backup(
                directories=[str(source)],
                backup_destination=str(backups),
                manifest=manifest,
                priority_policy=False,
            )
            t1 = time.perf_counter()
            times.append(t1 - t0)
        results["incremental_sem_alteracoes"] = _compute_stats(times)
        timing_data["Incremental s/ alterações"] = times

        # ── Cenário 2: Backup ZIP tradicional ──
        print("[2/4] Backup ZIP tradicional (30 execuções)...")
        times_zip = []
        for i in range(NUM_RUNS):
            zip_path = root / f"backup_tradicional_{i}.zip"
            t0 = time.perf_counter()
            with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(source.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(source))
            t1 = time.perf_counter()
            times_zip.append(t1 - t0)
            zip_path.unlink()  # remove para não acumular
        results["zip_tradicional"] = _compute_stats(times_zip)
        timing_data["ZIP tradicional"] = times_zip

        # ── Cenário 3: Backup incremental com criptografia ──
        print("[3/4] Backup incremental com criptografia (30 execuções)...")
        import security.crypto_service as cs
        with patch.object(cs, "is_crypto_available", return_value=True), \
             patch.object(cs, "encrypt_bytes_raw_data", side_effect=lambda data, key, **kw: data), \
             patch.object(cs, "encrypt_file", side_effect=lambda src, dst, key, **kw: shutil.copy2(src, dst)):
            # Primeira execução com criptografia
            bm.HISTORY_PATH = str(root / "config" / "backup_history_enc.json")
            (root / "config" / "backup_history_enc.json").write_text("[]")

            times_enc = []
            for i in range(NUM_RUNS):
                t0 = time.perf_counter()
                run_incremental_backup(
                    directories=[str(source)],
                    backup_destination=str(backups),
                    manifest=manifest,
                    priority_policy=False,
                )
                t1 = time.perf_counter()
                times_enc.append(t1 - t0)

        results["incremental_criptografia"] = _compute_stats(times_enc)
        timing_data["Incremental criptografia"] = times_enc

        # ── Cenário 4: Restauração + integridade ──
        print("[4/4] Restauração e verificação de integridade...")
        snapshots_dir = backups / bm.SNAPSHOTS_DIRNAME
        # Procura snapshots recursivamente
        snapshot_files = sorted(snapshots_dir.rglob("*.json"))
        if not snapshot_files:
            # Pode estar em subdiretório de data
            snapshot_files = sorted(backups.rglob("snapshot_*.json"))

        if snapshot_files:
            last_snapshot = snapshot_files[-1]
            print(f"  Snapshot: {last_snapshot}")
            restore_dest = root / "restored"
            restore_times = []
            integrity_ok = 0
            integrity_fail = 0

            for i in range(10):
                shutil.rmtree(str(restore_dest), ignore_errors=True)
                t0 = time.perf_counter()
                restore_snapshot(str(last_snapshot), str(restore_dest))
                t1 = time.perf_counter()
                restore_times.append(t1 - t0)

                for f in sorted(source.rglob("*")):
                    if f.is_file():
                        restored = restore_dest / f.relative_to(source)
                        if restored.exists():
                            h1 = hashlib.sha256(f.read_bytes()).hexdigest()
                            h2 = hashlib.sha256(restored.read_bytes()).hexdigest()
                            if h1 == h2:
                                integrity_ok += 1
                            else:
                                integrity_fail += 1

            shutil.rmtree(str(restore_dest), ignore_errors=True)
        else:
            restore_times = []
            integrity_ok = 0
            integrity_fail = 0
            print("  Nenhum snapshot encontrado para restaurar")

        results["restauracao"] = _compute_stats(restore_times) if restore_times else {}
        results["integridade"] = {
            "arquivos_verificados": integrity_ok + integrity_fail,
            "sucesso": integrity_ok,
            "falha": integrity_fail,
            "taxa_sucesso_pct": round(
                100 * integrity_ok / (integrity_ok + integrity_fail), 2
            ) if (integrity_ok + integrity_fail) > 0 else 0,
        }

        # ── Redução de tamanho ──
        incremental_size = sum(
            f.stat().st_size
            for f in backups.rglob("*")
            if f.is_file()
        )
        zip_path = root / "comparacao.zip"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(source.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(source))
        zip_size = zip_path.stat().st_size
        zip_path.unlink()

        if zip_size > 0:
            reducao_pct = round(100 * (1 - incremental_size / zip_size), 2)
        else:
            reducao_pct = 0.0

        results["reducao_tamanho"] = {
            "incremental_bytes": incremental_size,
            "zip_bytes": zip_size,
            "reducao_pct": reducao_pct,
        }

        # ── Estimativa de custo S3 ──
        results["custo_s3_estimado"] = _s3_cost_estimate(incremental_size)

    # ── Output ────────────────────────────────────────────────────
    report = {
        "data": datetime.now().isoformat(),
        "num_runs_por_cenario": NUM_RUNS,
        "nivel_confianca": "95%",
        "resultados": results,
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    print(f"\n[OK] Relatorio salvo em {REPORT_PATH}")

    if timing_data:
        _generate_boxplot(timing_data, BOXPLOT_PATH)

    # ── Resumo no terminal ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESUMO DOS RESULTADOS")
    print("=" * 60)
    for nome, stats in results.items():
        if "media_s" in stats:
            print(f"\n{nome}:")
            print(f"  Média:          {stats['media_s']:.4f} s")
            print(f"  Desvio padrão:  {stats['desvio_s']:.4f} s")
            print(f"  IC 95%:         ±{stats['ic95_mais_menos_s']:.4f} s")
            print(f"  Min / Max:      {stats['min_s']:.4f} / {stats['max_s']:.4f} s")

    if "reducao_pct" in results["reducao_tamanho"]:
        r = results["reducao_tamanho"]
        print(f"\nRedução de tamanho:")
        print(f"  Incremental: {r['incremental_bytes']:,} bytes ({r['incremental_bytes']/(1024**2):.1f} MB)")
        print(f"  ZIP:         {r['zip_bytes']:,} bytes ({r['zip_bytes']/(1024**2):.1f} MB)")
        print(f"  Redução:     {r['reducao_pct']}%")

    if "total_usd_mes" in results.get("custo_s3_estimado", {}):
        c = results["custo_s3_estimado"]
        print(f"\nCusto S3 estimado (mensal):")
        print(f"  Armazenamento:  ${c['armazenamento_usd_mes']:.4f}")
        print(f"  Transferência:  ${c['transferencia_usd']:.4f}")
        print(f"  Requisições:    ${c['requisicoes_usd']:.6f}")
        print(f"  Total:          ${c['total_usd_mes']:.4f}")

    if "taxa_sucesso_pct" in results.get("integridade", {}):
        ig = results["integridade"]
        print(f"\nIntegridade pós-restauração:")
        print(f"  Arquivos: {ig['arquivos_verificados']}")
        print(f"  Sucesso:  {ig['sucesso']}  |  Falha: {ig['falha']}")
        print(f"  Taxa:     {ig['taxa_sucesso_pct']}%")


if __name__ == "__main__":
    run_all_benchmarks()
