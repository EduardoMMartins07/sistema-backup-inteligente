import os
import socket
import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from api.config import get_settings


MIGRATION_NAME = "001_multiempresa_api"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS api_migrations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    hostname TEXT NOT NULL,
    identifier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(company_id, user_id, identifier),
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS monitored_folders (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    path TEXT NOT NULL,
    alias TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (device_id) REFERENCES devices(id)
);

CREATE TABLE IF NOT EXISTS backups (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    s3_key TEXT NOT NULL,
    checksum TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    local_path TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (folder_id) REFERENCES monitored_folders(id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    backup_id TEXT NOT NULL,
    name TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (folder_id) REFERENCES monitored_folders(id),
    FOREIGN KEY (backup_id) REFERENCES backups(id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    user_id TEXT,
    event TEXT NOT NULL,
    description TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_devices_company ON devices(company_id);
CREATE INDEX IF NOT EXISTS idx_folders_company ON monitored_folders(company_id);
CREATE INDEX IF NOT EXISTS idx_backups_company ON backups(company_id);
CREATE INDEX IF NOT EXISTS idx_backups_user ON backups(company_id, user_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_company ON snapshots(company_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_company ON audit_logs(company_id);
"""


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path():
    return get_settings().db_path


def _force_ipv4_url(database_url):
    """Resolve o hostname para IPv4 e substitui no lugar do hostname original.

    Necessario porque alguns provedores (ex: Supabase) expoem apenas registros
    AAAA (IPv6), e ambientes como Vercel serverless nao suportam conexao IPv6.
    """
    parsed = urlparse(database_url)
    hostname = parsed.hostname or ""

    if not hostname:
        return database_url

    try:
        # Tenta resolver IPv4; se falhar, mantem a URL original
        addrs = socket.getaddrinfo(hostname, parsed.port or 5432, socket.AF_INET)
        if not addrs:
            return database_url
        ipv4 = addrs[0][4][0]
    except socket.gaierror:
        return database_url

    if ipv4 == hostname:
        return database_url

    return database_url.replace(hostname, ipv4, 1)


class PostgresConnection:

    def __init__(self, database_url):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError(
                "Instale psycopg[binary] para usar DATABASE_URL PostgreSQL."
            ) from error

        self._psycopg = psycopg
        url = _force_ipv4_url(database_url)
        self._connection = psycopg.connect(url, row_factory=dict_row)

    def execute(self, sql, params=None):
        return self._connection.execute(self._translate_sql(sql), params)

    def executescript(self, script):
        for statement in _split_sql_statements(script):
            self.execute(statement)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    @staticmethod
    def _translate_sql(sql):
        translated = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", sql)
        translated = translated.replace("?", "%s")
        return translated


def _split_sql_statements(script):
    statements = []
    current = []

    for line in script.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.upper().startswith("PRAGMA "):
            continue

        current.append(line)

        if stripped.endswith(";"):
            statements.append("\n".join(current).rstrip(";"))
            current = []

    if current:
        statements.append("\n".join(current))

    return statements


def get_database_url(db_path=None):
    settings = get_settings()

    if db_path is not None:
        return f"sqlite:///{db_path}"

    return settings.database_url


def is_postgres_url(database_url):
    scheme = urlparse(database_url).scheme
    return scheme in {"postgres", "postgresql"}


def connect(db_path=None):
    database_url = get_database_url(db_path)

    if is_postgres_url(database_url):
        return PostgresConnection(database_url)

    db_path = db_path or get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path=None):
    connection = connect(db_path)

    try:
        connection.executescript(load_schema_sql())
        connection.execute(
            """
            INSERT INTO api_migrations (id, name, applied_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (MIGRATION_NAME, MIGRATION_NAME, utc_now()),
        )
        connection.commit()
    finally:
        connection.close()


def load_schema_sql():
    migration_path = MIGRATIONS_DIR / f"{MIGRATION_NAME}.sql"

    if migration_path.exists():
        return migration_path.read_text(encoding="utf-8")

    return SCHEMA_SQL


def get_db():
    connection = connect()

    try:
        yield connection
    finally:
        connection.close()


def row_to_dict(row):
    if row is None:
        return None

    if isinstance(row, dict):
        return dict(row)

    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows):
    return [row_to_dict(row) for row in rows]
