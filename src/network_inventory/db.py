"""SQLite connection and numbered migrations.

The schema version is stored in ``PRAGMA user_version``. A migration is a SQL file
named ``NNNN_name.sql`` in the ``migrations`` package directory, applied in order.
"""

import os
import re
import sqlite3
from importlib import resources
from pathlib import Path

DB_ENV = "NETWORK_INVENTORY_DB"
DEFAULT_DB = Path.home() / ".local" / "share" / "network-inventory" / "inventory.db"

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def db_path() -> Path:
    """Path of the database file: the environment variable, else the default."""
    return Path(os.environ.get(DB_ENV) or DEFAULT_DB)


def package_migrations() -> list[tuple[int, str]]:
    """The migrations shipped with the package, as (version, sql) sorted by version."""
    found = []
    for entry in resources.files("network_inventory").joinpath("migrations").iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database, create its folder, enforce foreign keys, and migrate it."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection, migrations: list[tuple[int, str]] | None = None) -> int:
    """Apply the migrations newer than the database version. Returns the new version."""
    migrations = package_migrations() if migrations is None else sorted(migrations)
    current = schema_version(conn)
    latest = migrations[-1][0] if migrations else 0
    if current > latest:
        raise RuntimeError(
            f"Database schema version {current} is newer than this program ({latest})."
        )
    for version, sql in migrations:
        if version <= current:
            continue
        # executescript commits first, so each migration and its version go in one script.
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {int(version)};\nCOMMIT;")
    return schema_version(conn)
