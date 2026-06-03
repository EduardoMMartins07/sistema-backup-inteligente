import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from api.database import _force_ipv4_url, close_postgres_pool, connect, init_db


class DatabaseUrlTests(unittest.TestCase):

    def test_neon_url_keeps_hostname_and_adds_endpoint_option(self):
        url = (
            "postgresql://user:pass@"
            "ep-wispy-moon-a1b2c3.sa-east-1.aws.neon.tech/db?sslmode=require"
        )

        translated = _force_ipv4_url(url)

        self.assertIn("ep-wispy-moon-a1b2c3.sa-east-1.aws.neon.tech", translated)
        self.assertIn("sslmode=require", translated)
        self.assertIn("options=endpoint%3Dep-wispy-moon-a1b2c3", translated)

    def test_neon_url_does_not_duplicate_existing_endpoint_option(self):
        url = (
            "postgresql://user:pass@"
            "ep-wispy-moon-a1b2c3.sa-east-1.aws.neon.tech/db"
            "?sslmode=require&options=endpoint%3Dep-wispy-moon-a1b2c3"
        )

        translated = _force_ipv4_url(url)

        self.assertEqual(url, translated)

    def test_non_neon_url_can_still_be_forced_to_ipv4(self):
        with patch("api.database.socket.getaddrinfo") as getaddrinfo:
            getaddrinfo.return_value = [(None, None, None, None, ("203.0.113.10", 5432))]

            translated = _force_ipv4_url(
                "postgresql://user:pass@db.example.com:5432/app"
            )

        self.assertEqual("postgresql://user:pass@203.0.113.10:5432/app", translated)

    def test_sqlite_connection_does_not_use_postgres_pool(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "api.sqlite3"

            with patch("api.database._get_postgres_pool") as get_pool:
                connection = connect(str(db_path))

                try:
                    self.assertIsInstance(connection, sqlite3.Connection)
                    self.assertFalse(get_pool.called)
                finally:
                    connection.close()

    def test_postgres_connection_uses_pool_and_returns_connection(self):
        class FakeRawConnection:
            def __init__(self):
                self.rollback_called = False

            def rollback(self):
                self.rollback_called = True

        class FakePool:
            def __init__(self):
                self.raw_connection = FakeRawConnection()
                self.returned_connection = None

            def getconn(self):
                return self.raw_connection

            def putconn(self, connection):
                self.returned_connection = connection

        pool = FakePool()

        with patch("api.database.get_database_url", return_value="postgresql://user:pass@db.example.com/app"):
            with patch("api.database._get_postgres_pool", return_value=pool) as get_pool:
                connection = connect()
                connection.close()

        self.assertTrue(get_pool.called)
        self.assertTrue(pool.raw_connection.rollback_called)
        self.assertIs(pool.raw_connection, pool.returned_connection)

    def test_web_performance_indexes_migration_is_applied(self):
        expected_indexes = {
            "idx_backups_company_created",
            "idx_backups_company_status_created",
            "idx_backups_company_device_created",
            "idx_devices_company_last_seen",
            "idx_audit_logs_company_created",
            "idx_snapshots_company_created",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "api.sqlite3"
            init_db(str(db_path))
            connection = connect(str(db_path))

            try:
                rows = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                ).fetchall()
            finally:
                connection.close()
                close_postgres_pool()

        index_names = {row["name"] for row in rows}
        self.assertTrue(expected_indexes.issubset(index_names))


if __name__ == "__main__":
    unittest.main()
