import pytest

from network_inventory import db, wifi
from network_inventory.inventory import ValidationError
from network_inventory.web.app import create_app

KEY = "s3cret-passphrase"


def network(ssid="Home", password=KEY, security="WPA", hidden=False):
    return wifi.WifiNetwork(1, ssid, password, security, hidden, "")


def test_payload_of_a_wpa_network():
    assert wifi.payload(network()) == f"WIFI:T:WPA;S:Home;P:{KEY};;"


def test_payload_marks_a_hidden_network():
    assert wifi.payload(network(hidden=True)).endswith(";H:true;;")


def test_payload_of_an_open_network_has_no_key():
    assert wifi.payload(network(password="", security="nopass")) == "WIFI:T:nopass;S:Home;;"


def test_payload_escapes_the_special_characters():
    text = wifi.payload(network(ssid='a;b,c:d"e\\f', password="p;w:d,x"))
    assert text == 'WIFI:T:WPA;S:a\;b\\,c\\:d\\"e\\\\f;P:p\;w\\:d\\,x;;'


def test_payload_quotes_a_value_made_only_of_hex_digits():
    assert (
        wifi.payload(network(ssid="cafe", password="12345678"))
        == 'WIFI:T:WPA;S:"cafe";P:"12345678";;'
    )


def test_qr_code_is_a_standalone_svg_that_a_browser_can_show():
    import xml.etree.ElementTree as ET

    svg = wifi.qr_svg(network())
    # Parsed as XML, and in the SVG namespace: without it an <img> shows nothing.
    root = ET.fromstring(svg)  # noqa: S314 (our own output, not untrusted data)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert "</svg>" in svg


def test_repr_does_not_leak_the_key():
    assert KEY not in repr(network())


@pytest.mark.parametrize(
    "ssid,password,security",
    [
        ("", KEY, "WPA"),
        ("x" * 33, KEY, "WPA"),
        ("Home", "short", "WPA"),
        ("Home", "", "WEP"),
        ("Home", KEY, "nope"),
    ],
)
def test_invalid_networks_are_refused(ssid, password, security):
    conn = db.connect(":memory:")
    with pytest.raises(ValidationError):
        wifi.create_network(conn, ssid, password, security)
    assert wifi.list_networks(conn) == []


def test_open_network_drops_any_key():
    conn = db.connect(":memory:")
    network_id = wifi.create_network(conn, "Guest", "ignored", "nopass")
    assert wifi.get_network(conn, network_id).password == ""


def test_ssid_is_unique():
    conn = db.connect(":memory:")
    wifi.create_network(conn, "Home", KEY, "WPA")
    with pytest.raises(ValidationError, match="already exists"):
        wifi.create_network(conn, "Home", KEY, "WPA")


def test_empty_key_on_update_keeps_the_current_key():
    conn = db.connect(":memory:")
    network_id = wifi.create_network(conn, "Home", KEY, "WPA")
    wifi.update_network(conn, network_id, "Home 2", "", "WPA", hidden=True)
    saved = wifi.get_network(conn, network_id)
    assert (saved.ssid, saved.password, saved.hidden) == ("Home 2", KEY, True)


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "wifi.db"
    conn = db.connect(path)
    wifi.create_network(conn, "Home", KEY, "WPA")
    conn.close()
    client = create_app(path).test_client()
    with client.session_transaction() as session:
        session["csrf"] = "token"
    return client


def test_key_is_not_in_the_pages_unless_asked(client):
    assert KEY not in client.get("/wifi").get_data(as_text=True)
    assert KEY not in client.get("/wifi/1").get_data(as_text=True)
    assert KEY in client.get("/wifi/1?reveal=1").get_data(as_text=True)


def test_qr_routes_serve_an_svg(client):
    response = client.get("/wifi/1/qr.svg")
    assert response.status_code == 200 and response.mimetype == "image/svg+xml"
    assert b'xmlns="http://www.w3.org/2000/svg"' in response.data
    assert response.headers["Cache-Control"] == "no-store"
    assert "qr.svg" in client.get("/wifi/1/qr").get_data(as_text=True)


def test_create_edit_delete_through_the_forms(client):
    response = client.post(
        "/wifi", data={"csrf_token": "token", "ssid": "Guest", "security": "WPA", "password": KEY}
    )
    assert response.status_code == 302
    assert "Guest" in client.get("/wifi").get_data(as_text=True)
    assert client.post("/wifi/2/delete", data={"csrf_token": "token"}).status_code == 302
    assert client.get("/wifi/2").status_code == 404


def test_invalid_form_shows_an_error_and_not_the_key(client):
    response = client.post(
        "/wifi", data={"csrf_token": "token", "ssid": "", "security": "WPA", "password": KEY}
    )
    page = response.get_data(as_text=True)
    assert response.status_code == 400 and "SSID" in page and KEY not in page


def test_wifi_post_needs_a_csrf_token(client):
    assert client.post("/wifi", data={"ssid": "x"}).status_code == 400
