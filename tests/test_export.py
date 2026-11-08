import json

import pytest

from network_inventory import db, export, inventory, wifi
from network_inventory.cli import main
from network_inventory.inventory import ValidationError
from network_inventory.web.app import create_app


@pytest.fixture
def conn():
    conn = db.connect(":memory:")
    pc = inventory.create_group(conn, "PC", [("192.0.2.10", "192.0.2.19")])
    free = inventory.create_group(conn, "Free", [("192.0.2.100", "192.0.2.199")], is_free=True)
    device = inventory.create_device(
        conn,
        "Desk|top",
        pc,
        [("aa:bb:cc:00:00:01", "192.0.2.10"), ("aa:bb:cc:00:00:02", None)],
        type="computer",
        notes="note",
    )
    inventory.update_interface(
        conn, inventory.get_device(conn, device).interfaces[1].id, "aa:bb:cc:00:00:02", None, "usb"
    )
    inventory.create_device(conn, "Phone", free, [("aa:bb:cc:00:00:03", "192.0.2.150")])
    wifi.create_network(conn, "Home", "s3cret-passphrase", "WPA", hidden=True, notes="main")
    return conn


def test_router_rows_are_sorted_by_ip_with_no_ip_last(conn):
    assert [r[0] for r in export.router_rows(conn)] == [
        "aa:bb:cc:00:00:01",
        "aa:bb:cc:00:00:03",
        "aa:bb:cc:00:00:02",
    ]


def test_csv_and_markdown(conn):
    rows = export.router_rows(conn)
    assert export.to_csv(rows).splitlines()[0] == "MAC,IP,NAME,GROUP"
    assert "aa:bb:cc:00:00:01,192.0.2.10,Desk|top,PC" in export.to_csv(rows)
    markdown = export.to_markdown(rows)
    assert "| MAC | IP | NAME | GROUP |" in markdown
    assert "Desk\\|top" in markdown


def test_backup_round_trip_restores_everything(conn):
    data = json.loads(export.to_json(export.backup(conn)))
    fresh = db.connect(":memory:")
    export.restore(fresh, data)
    assert export.backup(fresh) == export.backup(conn)
    assert wifi.list_networks(fresh)[0].password == "s3cret-passphrase"


def test_backup_can_leave_the_wifi_keys_out(conn):
    text = export.to_json(export.backup(conn, include_wifi_keys=False))
    assert "s3cret-passphrase" not in text


def test_restore_refuses_a_non_empty_inventory(conn):
    with pytest.raises(ValidationError, match="not empty"):
        export.restore(conn, export.backup(conn))


def test_a_bad_backup_leaves_the_database_untouched():
    data = {
        "version": 1,
        "groups": [{"name": "PC", "first_ip": "192.0.2.10", "last_ip": "192.0.2.19"}],
        "devices": [
            {
                "name": "A",
                "group": "PC",
                "interfaces": [{"mac": "aa:bb:cc:00:00:01", "ip": "192.0.2.99"}],
            }
        ],
    }
    fresh = db.connect(":memory:")
    with pytest.raises(ValidationError):
        export.restore(fresh, data)
    assert inventory.list_groups(fresh) == []


def test_unsupported_version_is_refused():
    with pytest.raises(ValidationError, match="version"):
        export.restore(db.connect(":memory:"), {"version": 99})


def test_cli_export_and_import(tmp_path, monkeypatch, capsys, conn):
    source = tmp_path / "source.db"
    real = db.connect(source)
    export.restore(real, export.backup(conn))
    real.close()
    monkeypatch.setenv(db.DB_ENV, str(source))
    assert main(["export", "--format", "json"]) == 0
    backup_file = tmp_path / "backup.json"
    backup_file.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "target.db"))
    assert main(["import", str(backup_file)]) == 0
    assert main(["export", "--format", "csv"]) == 0
    assert "Desk|top" in capsys.readouterr().out
    assert main(["import", str(backup_file)]) == 1


def test_web_downloads(tmp_path, conn):
    path = tmp_path / "web.db"
    real = db.connect(path)
    export.restore(real, export.backup(conn))
    real.close()
    client = create_app(path).test_client()
    csv_response = client.get("/export/router.csv")
    assert csv_response.headers["Content-Disposition"].startswith("attachment")
    assert "s3cret-passphrase" in client.get("/export/backup.json").get_data(as_text=True)
    assert "s3cret-passphrase" not in client.get("/export/backup.json?keys=0").get_data(
        as_text=True
    )
    assert client.get("/export").status_code == 200


def test_an_older_backup_with_one_range_per_group_still_imports():
    data = {
        "version": 1,
        "groups": [{"name": "PC", "first_ip": "192.0.2.10", "last_ip": "192.0.2.19"}],
        "devices": [],
    }
    fresh = db.connect(":memory:")
    export.restore(fresh, data)
    assert inventory.list_groups(fresh)[0].describe() == "192.0.2.10 to 192.0.2.19"


def test_backup_keeps_every_range_of_a_group():
    conn = db.connect(":memory:")
    inventory.create_group(conn, "I", [("192.0.2.1", "192.0.2.9"), ("192.0.2.254", "192.0.2.254")])
    fresh = db.connect(":memory:")
    export.restore(fresh, export.backup(conn))
    assert (
        inventory.list_groups(fresh)[0].describe()
        == "192.0.2.1 to 192.0.2.9, 192.0.2.254 to 192.0.2.254"
    )
