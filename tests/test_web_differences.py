import pytest

from network_inventory import db, inventory, scanner
from network_inventory.web.app import create_app


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "diff.db"
    conn = db.connect(path)
    pc = inventory.create_group(conn, "PC", "192.0.2.10", "192.0.2.19")
    inventory.create_group(conn, "Free", "192.0.2.100", "192.0.2.199", is_free=True)
    inventory.create_device(conn, "Desktop", pc, [("aa:bb:cc:00:00:01", "192.0.2.10")])
    inventory.create_device(conn, "Laptop", pc, [("aa:bb:cc:00:00:02", "192.0.2.11")])
    scan = scanner.parse_arp_scan(
        "192.0.2.10\taa:bb:cc:00:00:01\tV\n"
        "192.0.2.150\tde:ad:be:ef:00:01\tVendor X\n"
        "192.0.2.77\tde:ad:be:ef:00:02\tVendor Y\n"
    )
    scanner.store_observations(conn, scan, "2026-01-01T10:00:00Z")
    conn.close()
    client = create_app(path).test_client()
    with client.session_transaction() as session:
        session["csrf"] = "token"
    return client, path


def test_page_lists_each_kind_of_difference(setup):
    client, _ = setup
    page = client.get("/differences").get_data(as_text=True)
    assert "New devices" in page and "Unknown MAC" in page and "Missing" in page
    assert "Laptop" in page and "Vendor X" in page
    assert "2026-01-01T10:00:00Z" in page


def test_page_without_scan_says_so(tmp_path):
    page = create_app(tmp_path / "x.db").test_client().get("/differences").get_data(as_text=True)
    assert "No scan yet." in page


def test_attach_adds_a_network_card_to_a_device(setup):
    client, path = setup
    conn = db.connect(path)
    laptop = next(d for d in inventory.list_devices(conn) if d.name == "Laptop")
    response = client.post(
        "/differences/attach",
        data={
            "csrf_token": "token",
            "mac": "de:ad:be:ef:00:02",
            "device_id": str(laptop.id),
            "ip": "192.0.2.12",
        },
    )
    assert response.status_code == 302
    laptop = inventory.get_device(conn, laptop.id)
    assert [i.mac for i in laptop.interfaces] == ["aa:bb:cc:00:00:02", "de:ad:be:ef:00:02"]


def test_attach_with_an_invalid_ip_changes_nothing(setup):
    client, path = setup
    conn = db.connect(path)
    laptop = next(d for d in inventory.list_devices(conn) if d.name == "Laptop")
    client.post(
        "/differences/attach",
        data={
            "csrf_token": "token",
            "mac": "de:ad:be:ef:00:02",
            "device_id": str(laptop.id),
            "ip": "192.0.2.99",
        },
    )
    assert len(inventory.get_device(conn, laptop.id).interfaces) == 1


def test_attach_needs_a_csrf_token(setup):
    client, _ = setup
    assert client.post("/differences/attach", data={"mac": "x"}).status_code == 400


def test_failed_scan_is_reported_not_raised(setup, monkeypatch):
    client, _ = setup

    def fail(_interface=None):
        raise scanner.ScanError("no permission")

    monkeypatch.setattr(scanner, "run_arp_scan", fail)
    response = client.post("/scan", data={"csrf_token": "token"}, follow_redirects=True)
    assert "Scan failed: no permission" in response.get_data(as_text=True)


def test_new_device_form_is_prefilled_from_the_query(setup):
    client, _ = setup
    page = client.get("/devices/new?mac=de:ad:be:ef:00:01&ip=192.0.2.150").get_data(as_text=True)
    assert 'value="de:ad:be:ef:00:01"' in page
