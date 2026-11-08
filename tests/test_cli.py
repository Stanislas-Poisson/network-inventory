import pytest

from network_inventory import db, inventory, scanner
from network_inventory.cli import main


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv(db.DB_ENV, str(path))
    return path


def test_main_without_command_prints_help(capsys):
    assert main([]) == 0
    assert "network-inventory" in capsys.readouterr().out


def test_export_lists_one_row_per_interface(database, capsys):
    conn = db.connect(database)
    group = inventory.create_group(conn, "PC", [("192.0.2.10", "192.0.2.19")])
    inventory.create_device(conn, "Desktop", group, [("aa:bb:cc:00:00:01", "192.0.2.10")])
    assert main(["export"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split("\t") == ["MAC", "IP", "NAME", "GROUP"]
    assert lines[1].split("\t") == ["aa:bb:cc:00:00:01", "192.0.2.10", "Desktop", "PC"]


def test_diff_without_scan_fails(database, capsys):
    assert main(["diff"]) == 1
    assert "No scan yet" in capsys.readouterr().err


def test_diff_reports_what_needs_attention(database, capsys):
    conn = db.connect(database)
    group = inventory.create_group(conn, "PC", [("192.0.2.10", "192.0.2.19")])
    inventory.create_device(conn, "Desktop", group, [("aa:bb:cc:00:00:01", "192.0.2.10")])
    scan = scanner.parse_arp_scan("192.0.2.77\tde:ad:be:ef:00:01\tVendor\n")
    scanner.store_observations(conn, scan, "2026-01-01T10:00:00Z")
    assert main(["diff"]) == 0
    out = capsys.readouterr().out
    assert "missing" in out and "Desktop" in out
    assert "unknown mac" in out and "could be: Desktop" in out
    assert "0 ok, 2 to look at." in out


def test_scan_reports_a_failure_clearly(monkeypatch, database, capsys):
    def fail(_interface=None):
        raise scanner.ScanError("no permission")

    monkeypatch.setattr(scanner, "run_arp_scan", fail)
    assert main(["scan"]) == 1
    assert "Scan failed: no permission" in capsys.readouterr().err
