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


def test_upgrade_keeps_the_devices_when_the_category_column_is_dropped():
    conn = sqlite3.connect(":memory:")
    migrations = db.package_migrations()
    db.migrate(conn, migrations[:2])
    conn.execute(
        "INSERT INTO groups (name, first_ip, last_ip) VALUES ('G', '192.0.2.1', '192.0.2.9')"
    )
    conn.execute("INSERT INTO devices (name, category, group_id) VALUES ('D', 'old', 1)")
    conn.commit()
    db.migrate(conn, migrations)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(devices)")]
    assert "category" not in columns
    assert conn.execute("SELECT name FROM devices").fetchone()[0] == "D"


def test_group_ranges_migration_keeps_the_existing_range_of_each_group(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrations = db.package_migrations()
    db.migrate(conn, [m for m in migrations if m[0] < 5])
    conn.execute(
        "INSERT INTO groups (name, first_ip, last_ip) VALUES ('G', '192.0.2.1', '192.0.2.9')"
    )
    conn.commit()
    db.migrate(conn, migrations)
    assert conn.execute("SELECT first_ip, last_ip FROM group_ranges").fetchone()[:] == (
        "192.0.2.1",
        "192.0.2.9",
    )
    columns = [r[1] for r in conn.execute("PRAGMA table_info(groups)")]
    assert "first_ip" not in columns and "last_ip" not in columns


def test_a_copy_is_made_before_a_database_with_data_is_upgraded(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    db.migrate(old, [m for m in db.package_migrations() if m[0] < 5])
    old.execute(
        "INSERT INTO groups (name, first_ip, last_ip) VALUES ('G', '192.0.2.1', '192.0.2.9')"
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    copy = tmp_path / "old.db.backup-v4"
    assert copy.exists() and (copy.stat().st_mode & 0o777) == 0o600
    saved = sqlite3.connect(copy)
    assert saved.execute("PRAGMA user_version").fetchone()[0] == 4
    assert saved.execute("SELECT first_ip FROM groups").fetchone()[0] == "192.0.2.1"
    assert db.schema_version(conn) == db.package_migrations()[-1][0]


def test_no_copy_for_a_new_or_an_up_to_date_database(tmp_path):
    path = tmp_path / "new.db"
    db.connect(path).close()
    db.connect(path).close()
    assert list(tmp_path.glob("*.backup-*")) == []
