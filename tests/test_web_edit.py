import stat

import pytest

from network_inventory import db, inventory
from network_inventory.web.app import create_app


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "edit.db"
    app = create_app(path)
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = "token"
    return client, path


def conn_of(path):
    return db.connect(path)


def post(client, url, **data):
    return client.post(url, data={"csrf_token": "token", **data})


def test_post_without_csrf_token_is_refused(setup):
    client, path = setup
    response = client.post(
        "/groups", data={"name": "PC", "first_ip": "192.0.2.10", "last_ip": "192.0.2.19"}
    )
    assert response.status_code == 400
    assert inventory.list_groups(conn_of(path)) == []


def test_post_with_a_wrong_token_is_refused(setup):
    client, _ = setup
    assert client.post("/groups", data={"csrf_token": "nope"}).status_code == 400


def test_secret_key_file_is_private(setup):
    _, path = setup
    mode = (path.with_name(path.name + ".secret")).stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_create_edit_and_delete_a_group(setup):
    client, path = setup
    response = post(client, "/groups", name="PC", first_ip="192.0.2.10", last_ip="192.0.2.19")
    assert response.status_code == 302
    group = inventory.list_groups(conn_of(path))[0]
    response = post(
        client,
        f"/groups/{group.id}",
        name="PCs",
        first_ip="192.0.2.10",
        last_ip="192.0.2.29",
        is_free="on",
    )
    assert response.status_code == 302
    saved = inventory.get_group(conn_of(path), group.id)
    assert (saved.name, saved.last_ip, saved.is_free) == ("PCs", "192.0.2.29", True)
    post(client, f"/groups/{group.id}/delete")
    assert inventory.list_groups(conn_of(path)) == []


def test_invalid_group_shows_the_error_and_keeps_the_input(setup):
    client, path = setup
    post(client, "/groups", name="PC", first_ip="192.0.2.10", last_ip="192.0.2.19")
    response = post(client, "/groups", name="Other", first_ip="192.0.2.15", last_ip="192.0.2.25")
    page = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "overlaps" in page and 'value="Other"' in page
    assert len(inventory.list_groups(conn_of(path))) == 1


def test_error_messages_are_escaped(setup):
    client, _ = setup
    response = post(client, "/groups", name="<b>x</b>", first_ip="nope", last_ip="192.0.2.1")
    page = response.get_data(as_text=True)
    assert "<b>x</b>" not in page


def test_new_device_form_suggests_the_first_free_ip(setup):
    client, path = setup
    group = inventory.create_group(conn_of(path), "PC", "192.0.2.10", "192.0.2.19")
    inventory.create_device(conn_of(path), "A", group, [("aa:bb:cc:00:00:01", "192.0.2.10")])
    page = client.get(f"/devices/new?group={group}").get_data(as_text=True)
    assert "First free IP of this group: 192.0.2.11" in page


def test_device_and_interfaces_lifecycle(setup):
    client, path = setup
    group = inventory.create_group(conn_of(path), "PC", "192.0.2.10", "192.0.2.19")
    response = post(
        client,
        "/devices/new",
        name="Desktop",
        group_id=str(group),
        mac="AA:BB:CC:00:00:01",
        ip="192.0.2.10",
    )
    assert response.status_code == 302
    device = inventory.list_devices(conn_of(path))[0]

    post(
        client,
        f"/devices/{device.id}/interfaces",
        mac="aa:bb:cc:00:00:02",
        ip="192.0.2.11",
        label="usb",
    )
    device = inventory.get_device(conn_of(path), device.id)
    assert [i.mac for i in device.interfaces] == ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]

    second = device.interfaces[1]
    post(client, f"/interfaces/{second.id}", mac=second.mac, ip="192.0.2.12", label="usb")
    assert inventory.get_device(conn_of(path), device.id).interfaces[1].expected_ip == "192.0.2.12"

    post(client, f"/interfaces/{second.id}/delete")
    assert len(inventory.get_device(conn_of(path), device.id).interfaces) == 1

    post(client, f"/devices/{device.id}/delete")
    assert inventory.list_devices(conn_of(path)) == []


def test_invalid_device_is_refused_with_a_message(setup):
    client, path = setup
    group = inventory.create_group(conn_of(path), "PC", "192.0.2.10", "192.0.2.19")
    response = post(
        client,
        "/devices/new",
        name="D",
        group_id=str(group),
        mac="aa:bb:cc:00:00:01",
        ip="192.0.2.99",
    )
    assert response.status_code == 400
    assert "outside the range" in response.get_data(as_text=True)
    assert inventory.list_devices(conn_of(path)) == []


def test_unknown_ids_give_404(setup):
    client, _ = setup
    assert client.get("/devices/999").status_code == 404
    assert client.get("/groups/999").status_code == 404
    assert post(client, "/interfaces/999/delete").status_code == 404


def test_device_form_suggests_the_types_already_used(setup):
    client, path = setup
    group = inventory.create_group(conn_of(path), "PC", "192.0.2.10", "192.0.2.19")
    inventory.create_device(conn_of(path), "A", group, type="laptop")
    page = client.get("/devices/new").get_data(as_text=True)
    assert '<option value="laptop">' in page
