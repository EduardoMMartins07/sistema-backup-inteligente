import argparse
import csv
import hashlib
import os
import random
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from statistics import mean
from statistics import stdev

from backup import backup_manager
from cloud import aws_s3_service
from security import crypto_service


KiB = 1024
MiB = 1024 * KiB


@dataclass(frozen=True)
class Scenario:
    name: str
    file_count: int
    file_sizes: tuple[int, ...]
    duplicate_rate: float
    change_rate: float


@dataclass(frozen=True)
class DatasetInfo:
    source_dir: Path
    total_files: int
    duplicate_files: int
    changed_files: int
    raw_size_bytes: int


SCENARIOS = {
    "small": Scenario("small", 100, (16 * KiB,), 0.30, 0.10),
    "medium": Scenario("medium", 500, (64 * KiB,), 0.30, 0.10),
    "mixed": Scenario("mixed", 300, (4 * KiB, 64 * KiB, 1 * MiB), 0.25, 0.15),
}


FIELDNAMES = [
    "scenario",
    "run",
    "strategy",
    "phase",
    "duration_seconds",
    "source_size_bytes",
    "backup_size_bytes",
    "storage_reduction_percent",
    "total_files",
    "objects_stored",
    "objects_referenced",
    "files_unchanged",
    "files_changed",
    "warnings_count",
    "overhead_percent",
    "cloud_sync_status",
    "cloud_error_message",
]


class FailingS3Client:
    def head_bucket(self, Bucket):
        return None

    def put_object(self, Bucket, Key, Body):
        raise RuntimeError("AccessDenied: simulated-network-failure")

    def delete_object(self, Bucket, Key):
        return None

    def upload_file(self, Filename, Bucket, Key, Config=None):
        raise RuntimeError("AccessDenied: simulated-network-failure")


def deterministic_bytes(label, size):
    payload = bytearray()
    counter = 0

    while len(payload) < size:
        block = hashlib.sha256(f"{label}:{counter}".encode("utf-8")).digest()
        payload.extend(block)
        counter += 1

    return bytes(payload[:size])


def scenario_file_size(scenario, index):
    return scenario.file_sizes[index % len(scenario.file_sizes)]


def generate_synthetic_dataset(root_dir, scenario, seed=42):
    root_dir = Path(root_dir)
    source_dir = root_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    randomizer = random.Random(seed)
    duplicate_files = int(scenario.file_count * scenario.duplicate_rate)
    unique_files = scenario.file_count - duplicate_files
    unique_payloads = []

    for index in range(unique_files):
        size = scenario_file_size(scenario, index)
        payload = deterministic_bytes(f"{scenario.name}:unique:{seed}:{index}", size)
        relative_dir = source_dir / f"group_{index % 10:02d}"
        relative_dir.mkdir(parents=True, exist_ok=True)
        file_path = relative_dir / f"file_{index:04d}.bin"
        file_path.write_bytes(payload)
        unique_payloads.append((payload, size))

    for offset in range(duplicate_files):
        source_index = randomizer.randrange(unique_files)
        payload, _ = unique_payloads[source_index]
        file_index = unique_files + offset
        relative_dir = source_dir / f"group_{file_index % 10:02d}"
        relative_dir.mkdir(parents=True, exist_ok=True)
        file_path = relative_dir / f"file_{file_index:04d}_dup.bin"
        file_path.write_bytes(payload)

    return DatasetInfo(
        source_dir=source_dir,
        total_files=scenario.file_count,
        duplicate_files=duplicate_files,
        changed_files=int(scenario.file_count * scenario.change_rate),
        raw_size_bytes=size_directory(source_dir),
    )


def mutate_synthetic_dataset(source_dir, change_count, seed=42):
    files = sorted(Path(source_dir).rglob("*.bin"))
    selected = random.Random(seed + 1000).sample(files, min(change_count, len(files)))

    for index, file_path in enumerate(selected):
        size = file_path.stat().st_size
        file_path.write_bytes(deterministic_bytes(f"changed:{seed}:{index}", size))

    return len(selected)


def size_directory(path):
    path = Path(path)

    if not path.exists():
        return 0

    return sum(file_path.stat().st_size for file_path in path.rglob("*") if file_path.is_file())


def storage_reduction_percent(source_size_bytes, backup_size_bytes):
    if source_size_bytes <= 0:
        return 0.0

    return (1 - (backup_size_bytes / source_size_bytes)) * 100


def calculate_overhead_percent(base_duration, measured_duration):
    if base_duration <= 0:
        return 0.0

    return ((measured_duration - base_duration) / base_duration) * 100


def timed_call(function, *args, **kwargs):
    started = time.perf_counter()
    result = function(*args, **kwargs)
    return time.perf_counter() - started, result


def build_manifest(source_dir, backup_destination):
    return backup_manager.build_backup_manifest(
        directories=[str(source_dir)],
        backup_destination=str(backup_destination),
    )


def count_changed_files(result):
    counts = result.get("status_counts", {})
    return counts.get("stored_new_object", 0) + counts.get("referenced_existing_object", 0)


def benchmark_row(
    scenario,
    run_index,
    strategy,
    phase,
    duration_seconds,
    source_size_bytes,
    backup_size_bytes,
    result=None,
    overhead_percent="",
    cloud_sync_status="",
    cloud_error_message="",
):
    result = result or {}
    return {
        "scenario": scenario.name,
        "run": run_index,
        "strategy": strategy,
        "phase": phase,
        "duration_seconds": f"{duration_seconds:.6f}",
        "source_size_bytes": source_size_bytes,
        "backup_size_bytes": backup_size_bytes,
        "storage_reduction_percent": f"{storage_reduction_percent(source_size_bytes, backup_size_bytes):.4f}",
        "total_files": result.get("total_files", ""),
        "objects_stored": result.get("objects_stored", ""),
        "objects_referenced": result.get("objects_referenced", ""),
        "files_unchanged": result.get("files_unchanged", ""),
        "files_changed": count_changed_files(result) if result else "",
        "warnings_count": len(result.get("warnings", [])) if result else "",
        "overhead_percent": "" if overhead_percent == "" else f"{overhead_percent:.4f}",
        "cloud_sync_status": cloud_sync_status,
        "cloud_error_message": cloud_error_message,
    }


@contextmanager
def isolated_dataset_path(root_dir):
    original_dataset_path = backup_manager.DATASET_PATH
    backup_manager.DATASET_PATH = str(Path(root_dir) / "missing_files_dataset.csv")

    try:
        yield
    finally:
        backup_manager.DATASET_PATH = original_dataset_path


def run_zip_baseline(scenario, run_index, source_dir, destination, source_size_bytes, now):
    manifest = build_manifest(source_dir, destination)
    duration, result = timed_call(
        backup_manager.create_versioned_backup,
        directories=[str(source_dir)],
        backup_destination=str(destination),
        manifest=manifest,
        now=now,
    )
    zip_path, warnings = result
    zip_size = os.path.getsize(zip_path)
    row_result = {
        "total_files": len(manifest),
        "warnings": warnings,
    }
    return benchmark_row(
        scenario,
        run_index,
        "zip_traditional",
        "full_backup",
        duration,
        source_size_bytes,
        zip_size,
        row_result,
    )


def run_incremental_sequence(scenario, run_index, dataset, destination, now, seed):
    rows = []
    source_dir = dataset.source_dir
    manifest = build_manifest(source_dir, destination)
    duration_initial, initial_result = timed_call(
        backup_manager.run_incremental_backup,
        directories=[str(source_dir)],
        backup_destination=str(destination),
        manifest=manifest,
        now=now,
    )
    rows.append(
        benchmark_row(
            scenario,
            run_index,
            "incremental",
            "initial_backup",
            duration_initial,
            dataset.raw_size_bytes,
            size_directory(destination),
            initial_result,
        )
    )

    duration_no_changes, no_changes_result = timed_call(
        backup_manager.run_incremental_backup,
        directories=[str(source_dir)],
        backup_destination=str(destination),
        manifest=manifest,
        now=now + timedelta(seconds=1),
    )
    rows.append(
        benchmark_row(
            scenario,
            run_index,
            "incremental",
            "no_changes_backup",
            duration_no_changes,
            dataset.raw_size_bytes,
            size_directory(destination),
            no_changes_result,
        )
    )

    changed_files = mutate_synthetic_dataset(source_dir, dataset.changed_files, seed=seed)
    changed_source_size = size_directory(source_dir)
    changed_manifest = build_manifest(source_dir, destination)
    duration_changed, changed_result = timed_call(
        backup_manager.run_incremental_backup,
        directories=[str(source_dir)],
        backup_destination=str(destination),
        manifest=changed_manifest,
        now=now + timedelta(seconds=2),
    )
    changed_result["changed_files_expected"] = changed_files
    rows.append(
        benchmark_row(
            scenario,
            run_index,
            "incremental",
            "changed_backup",
            duration_changed,
            changed_source_size,
            size_directory(destination),
            changed_result,
        )
    )

    restore_destination = destination.parent / "restore"
    duration_restore, restore_result = timed_call(
        backup_manager.restore_snapshot,
        changed_result["snapshot_path"],
        str(restore_destination),
    )
    rows.append(
        benchmark_row(
            scenario,
            run_index,
            "incremental",
            "restore",
            duration_restore,
            changed_source_size,
            size_directory(restore_destination),
            {"total_files": len(restore_result), "warnings": []},
        )
    )

    export_path = destination.parent / "exports" / "snapshot_export.zip"
    duration_export, export_result = timed_call(
        backup_manager.export_snapshot_to_zip,
        changed_result["snapshot_path"],
        str(export_path),
    )
    rows.append(
        benchmark_row(
            scenario,
            run_index,
            "incremental",
            "export_zip",
            duration_export,
            changed_source_size,
            os.path.getsize(export_path),
            {"total_files": export_result.get("files_exported", 0), "warnings": export_result.get("warnings", [])},
        )
    )

    return rows, duration_initial, changed_result, changed_source_size


def run_encryption_overhead(scenario, run_index, source_dir, destination, source_size_bytes, now, base_duration):
    if not crypto_service.is_crypto_available():
        return None

    manifest = build_manifest(source_dir, destination)
    master_key = crypto_service.generate_key()
    duration, encrypted_result = timed_call(
        backup_manager.run_incremental_backup,
        directories=[str(source_dir)],
        backup_destination=str(destination),
        manifest=manifest,
        now=now,
        encryption_context={
            "master_key": master_key,
            "user_id": "benchmark",
            "company_id": "tcc",
        },
    )
    return benchmark_row(
        scenario,
        run_index,
        "incremental_encrypted",
        "initial_backup",
        duration,
        source_size_bytes,
        size_directory(destination),
        encrypted_result,
        overhead_percent=calculate_overhead_percent(base_duration, duration),
    )


def run_cloud_failure_probe(scenario, run_index, incremental_result, source_size_bytes, backup_size_bytes):
    history_entry = {
        "timestamp": "08/05/2026 08:00:00",
        "backup_path": incremental_result["snapshot_path"],
        "snapshot_path": incremental_result["snapshot_path"],
        "backup_storage": incremental_result["backup_storage"],
        "index_path": incremental_result["index_path"],
        "storage_mode": "incremental",
        "file_snapshot": incremental_result["file_snapshot"],
        "user": "benchmark",
        "company_id": "tcc",
    }
    settings = {
        "enabled": True,
        "bucket_name": "benchmark-bucket",
        "region": "us-east-1",
        "base_prefix": "backups",
        "access_key_id": "benchmark",
        "secret_access_key": "benchmark-secret",
    }
    duration, cloud_result = timed_call(
        aws_s3_service.sync_backup_to_s3,
        history_entry,
        settings=settings,
        client=FailingS3Client(),
    )
    return benchmark_row(
        scenario,
        run_index,
        "cloud_s3",
        "upload_failure",
        duration,
        source_size_bytes,
        backup_size_bytes,
        {"warnings": []},
        cloud_sync_status=cloud_result.get("cloud_sync_status", ""),
        cloud_error_message=cloud_result.get("cloud_error_message", ""),
    )


def run_scenario_once(scenario, run_index, seed=42):
    rows = []
    now = datetime(2026, 5, 8, 8, 0, min(run_index, 50))

    with tempfile.TemporaryDirectory(prefix=f"smartbackup_{scenario.name}_") as temp_name:
        temp_root = Path(temp_name)
        dataset = generate_synthetic_dataset(temp_root, scenario, seed=seed + run_index)

        with isolated_dataset_path(temp_root):
            zip_destination = temp_root / "zip_baseline"
            rows.append(
                run_zip_baseline(
                    scenario,
                    run_index,
                    dataset.source_dir,
                    zip_destination,
                    dataset.raw_size_bytes,
                    now,
                )
            )

            incremental_destination = temp_root / "incremental"
            incremental_rows, base_duration, changed_result, changed_source_size = run_incremental_sequence(
                scenario,
                run_index,
                dataset,
                incremental_destination,
                now,
                seed + run_index,
            )
            rows.extend(incremental_rows)

            encrypted_destination = temp_root / "incremental_encrypted"
            encrypted_row = run_encryption_overhead(
                scenario,
                run_index,
                dataset.source_dir,
                encrypted_destination,
                changed_source_size,
                now + timedelta(seconds=3),
                base_duration,
            )

            if encrypted_row:
                rows.append(encrypted_row)

            rows.append(
                run_cloud_failure_probe(
                    scenario,
                    run_index,
                    changed_result,
                    changed_source_size,
                    size_directory(incremental_destination),
                )
            )

    return rows


def write_csv(rows, csv_path):
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def grouped_summary(rows):
    groups = {}

    for row in rows:
        key = (row["scenario"], row["strategy"], row["phase"])
        groups.setdefault(key, []).append(row)

    summaries = []

    for (scenario, strategy, phase), group_rows in sorted(groups.items()):
        durations = [float(row["duration_seconds"]) for row in group_rows]
        reductions = [float(row["storage_reduction_percent"]) for row in group_rows]
        backup_sizes = [int(row["backup_size_bytes"]) for row in group_rows]
        summaries.append(
            {
                "scenario": scenario,
                "strategy": strategy,
                "phase": phase,
                "runs": len(group_rows),
                "duration_mean": mean(durations),
                "duration_stdev": stdev(durations) if len(durations) > 1 else 0.0,
                "backup_size_mean": mean(backup_sizes),
                "reduction_mean": mean(reductions),
            }
        )

    return summaries


def write_markdown_summary(rows, markdown_path):
    markdown_path = Path(markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    summaries = grouped_summary(rows)

    lines = [
        "# Resumo da Avaliacao Experimental",
        "",
        "Resultados gerados por `python -m experiments.benchmark_backup` com dataset sintetico deterministico.",
        "",
        "| Cenario | Estrategia | Fase | Runs | Tempo medio (s) | Desvio (s) | Tamanho medio (bytes) | Reducao media (%) |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]

    for item in summaries:
        lines.append(
            "| {scenario} | {strategy} | {phase} | {runs} | {duration_mean:.6f} | {duration_stdev:.6f} | {backup_size_mean:.0f} | {reduction_mean:.2f} |".format(
                **item
            )
        )

    cloud_failures = [
        row for row in rows
        if row["strategy"] == "cloud_s3" and row["phase"] == "upload_failure"
    ]

    if cloud_failures:
        statuses = ", ".join(sorted({row["cloud_sync_status"] for row in cloud_failures}))
        lines.extend(
            [
                "",
                "## Falha de Rede Simulada",
                "",
                f"As execucoes de upload para S3 falso retornaram status: `{statuses}`.",
                "Esse cenario valida que o backup local permanece mensuravel mesmo quando a sincronizacao em nuvem falha.",
            ]
        )

    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(runs=5, output_dir=None, scenario_names=None, seed=42):
    output_dir = Path(output_dir or Path(__file__).parent / "results")
    scenario_names = scenario_names or list(SCENARIOS)
    rows = []

    for scenario_name in scenario_names:
        scenario = SCENARIOS[scenario_name]

        for run_index in range(1, runs + 1):
            rows.extend(run_scenario_once(scenario, run_index, seed=seed))

    csv_path = output_dir / "benchmark_results.csv"
    markdown_path = output_dir / "benchmark_summary.md"
    write_csv(rows, csv_path)
    write_markdown_summary(rows, markdown_path)
    return {
        "rows": rows,
        "csv_path": str(csv_path),
        "markdown_path": str(markdown_path),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Executa avaliacao quantitativa do backup incremental."
    )
    parser.add_argument("--runs", type=int, default=5, help="Numero de repeticoes por cenario.")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent / "results"),
        help="Diretorio de saida dos arquivos CSV e Markdown.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="Cenario a executar. Pode ser informado mais de uma vez.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Seed base dos datasets sinteticos.")
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_benchmark(
        runs=args.runs,
        output_dir=args.output_dir,
        scenario_names=args.scenario,
        seed=args.seed,
    )
    print(f"CSV: {result['csv_path']}")
    print(f"Markdown: {result['markdown_path']}")


if __name__ == "__main__":
    main()
