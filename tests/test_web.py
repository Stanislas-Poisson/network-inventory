import pytest

from network_inventory import db, inventory
from network_inventory.web.app import create_app


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "web.db"
    conn = db.connect(path)
    pc = inventory.create_group(conn, "PC", [("192.0.2.10", "192.0.2.19")])
    iot = inventory.create_group(conn, "IoT", [("192.0.2.40", "192.0.2.49")])
    inventory.create_device(
        conn, "Desktop", pc, [("aa:bb:cc:00:00:01", "192.0.2.10")], type="computer"
    )
    inventory.create_device(conn, "Lamp", iot, [("aa:bb:cc:00:00:02", "192.0.2.41")], type="light")
    conn.close()
    return create_app(path).test_client()


def test_default_view_groups_devices_by_group_range_order(client):
    page = client.get("/").get_data(as_text=True)
    assert page.index("PC") < page.index("Desktop") < page.index("IoT") < page.index("Lamp")
    assert "192.0.2.10 to 192.0.2.19" in page


@pytest.mark.parametrize("view", ["group", "type", "ip", "name"])
def test_every_view_renders_every_device(client, view):
    response = client.get(f"/?by={view}")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Desktop" in page and "Lamp" in page


def test_unknown_view_falls_back_to_group(client):
    assert client.get("/?by=nope").status_code == 200


def test_values_are_escaped(tmp_path):
    path = tmp_path / "xss.db"
    conn = db.connect(path)
    group = inventory.create_group(conn, "G", [("192.0.2.10", "192.0.2.19")])
    inventory.create_device(conn, "<script>alert(1)</script>", group)
    conn.close()
    page = create_app(path).test_client().get("/").get_data(as_text=True)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_empty_inventory_says_so(tmp_path):
    page = create_app(tmp_path / "empty.db").test_client().get("/").get_data(as_text=True)
    assert "The inventory is empty." in page
