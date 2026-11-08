import sqlite3

import pytest

from network_inventory import db


def test_fresh_database_gets_the_latest_version():
    conn = db.connect(":memory:")
    latest = db.package_migrations()[-1][0]
    assert db.schema_version(conn) == latest
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"groups", "devices", "interfaces", "observations"} <= tables


def test_foreign_keys_are_enforced():
    conn = db.connect(":memory:")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO devices (name, group_id) VALUES ('x', 999)")


def test_upgrade_applies_only_the_newer_migrations():
    conn = sqlite3.connect(":memory:")
    first = (1, "CREATE TABLE a (id INTEGER);")
    second = (2, "CREATE TABLE b (id INTEGER);")
    assert db.migrate(conn, [first]) == 1
    assert db.migrate(conn, [first, second]) == 2
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"a", "b"}


def test_failed_migration_leaves_the_version_untouched():
    conn = sqlite3.connect(":memory:")
    db.migrate(conn, [(1, "CREATE TABLE a (id INTEGER);")])
    with pytest.raises(sqlite3.Error):
        db.migrate(conn, [(1, "CREATE TABLE a (id INTEGER);"), (2, "NOT SQL;")])
    conn.rollback()
    assert db.schema_version(conn) == 1


def test_database_newer_than_the_program_is_refused():
    conn = sqlite3.connect(":memory:")
    db.migrate(conn, [(2, "CREATE TABLE a (id INTEGER);")])
    with pytest.raises(RuntimeError):
        db.migrate(conn, [(1, "CREATE TABLE a (id INTEGER);")])


def test_db_path_uses_the_environment_variable(monkeypatch, tmp_path):
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "x.db"))
    assert db.db_path() == tmp_path / "x.db"
