import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import benchmark_backup


class ExperimentalBenchmarkTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def file_hashes(self, source_dir):
        return {
            path.relative_to(source_dir).as_posix(): benchmark_backup.hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(Path(source_dir).rglob("*.bin"))
        }

    def test_synthetic_dataset_has_expected_duplicate_and_change_counts(self):
        scenario = benchmark_backup.Scenario(
            "tiny",
            file_count=10,
            file_sizes=(128,),
            duplicate_rate=0.30,
            change_rate=0.20,
        )

        dataset = benchmark_backup.generate_synthetic_dataset(
            self.root,
            scenario,
            seed=7,
        )
        before_hashes = self.file_hashes(dataset.source_dir)
        changed_count = benchmark_backup.mutate_synthetic_dataset(
            dataset.source_dir,
            dataset.changed_files,
            seed=7,
        )
        after_hashes = self.file_hashes(dataset.source_dir)

        self.assertEqual(10, dataset.total_files)
        self.assertEqual(3, dataset.duplicate_files)
        self.assertEqual(2, dataset.changed_files)
        self.assertEqual(10, len(before_hashes))
        self.assertEqual(7, len(set(before_hashes.values())))
        self.assertEqual(2, changed_count)
        self.assertEqual(
            2,
            sum(
                before_hashes[name] != after_hashes[name]
                for name in before_hashes
            ),
        )

    def test_metric_calculations_are_stable(self):
        self.assertEqual(
            75.0,
            benchmark_backup.storage_reduction_percent(400, 100),
        )
        self.assertEqual(
            50.0,
            benchmark_backup.calculate_overhead_percent(2.0, 3.0),
        )
        self.assertEqual(
            0.0,
            benchmark_backup.storage_reduction_percent(0, 100),
        )

    def test_writes_csv_and_markdown_reports(self):
        rows = [
            benchmark_backup.benchmark_row(
                benchmark_backup.Scenario("tiny", 1, (10,), 0, 0),
                1,
                "incremental",
                "initial_backup",
                0.25,
                100,
                40,
                {
                    "total_files": 1,
                    "objects_stored": 1,
                    "objects_referenced": 0,
                    "files_unchanged": 0,
                    "warnings": [],
                },
            )
        ]
        csv_path = self.root / "out" / "benchmark_results.csv"
        markdown_path = self.root / "out" / "benchmark_summary.md"

        benchmark_backup.write_csv(rows, csv_path)
        benchmark_backup.write_markdown_summary(rows, markdown_path)

        with csv_path.open("r", encoding="utf-8", newline="") as file:
            parsed = list(csv.DictReader(file))

        self.assertEqual("tiny", parsed[0]["scenario"])
        self.assertEqual("60.0000", parsed[0]["storage_reduction_percent"])
        self.assertIn(
            "Resumo da Avaliacao Experimental",
            markdown_path.read_text(encoding="utf-8"),
        )

    def test_cloud_failure_probe_uses_fake_client_without_network(self):
        backup_storage = self.root / "storage"
        snapshot_path = backup_storage / "snapshots" / "snapshot.json"
        index_path = backup_storage / "index.json"
        snapshot_path.parent.mkdir(parents=True)
        snapshot_path.write_text(
            json.dumps(
                {
                    "snapshot_id": "snapshot",
                    "storage_root": str(backup_storage),
                    "index_path": str(index_path),
                    "files": [],
                }
            ),
            encoding="utf-8",
        )
        index_path.write_text("{}", encoding="utf-8")
        incremental_result = {
            "snapshot_path": str(snapshot_path),
            "backup_storage": str(backup_storage),
            "index_path": str(index_path),
            "file_snapshot": {},
        }

        row = benchmark_backup.run_cloud_failure_probe(
            benchmark_backup.Scenario("tiny", 1, (10,), 0, 0),
            1,
            incremental_result,
            100,
            50,
        )

        self.assertEqual("falhou", row["cloud_sync_status"])
        self.assertEqual("AccessDenied", row["cloud_error_message"])

    def test_run_benchmark_creates_reports_in_configured_directory(self):
        tiny_scenario = benchmark_backup.Scenario(
            "tiny",
            file_count=6,
            file_sizes=(128, 256),
            duplicate_rate=0.33,
            change_rate=0.33,
        )
        output_dir = self.root / "results"

        with patch.dict(benchmark_backup.SCENARIOS, {"tiny": tiny_scenario}, clear=True):
            result = benchmark_backup.run_benchmark(
                runs=1,
                output_dir=output_dir,
                scenario_names=["tiny"],
                seed=11,
            )

        self.assertTrue(Path(result["csv_path"]).exists())
        self.assertTrue(Path(result["markdown_path"]).exists())
        self.assertGreaterEqual(len(result["rows"]), 6)


if __name__ == "__main__":
    unittest.main()
