import base64
import stat

import pytest

from network_inventory import db
from network_inventory.cli import main
from network_inventory.web import auth
from network_inventory.web.app import create_app

PASSWORD = "correct horse battery"


def basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def protected(tmp_path):
    path = tmp_path / "auth.db"
    auth.set_password(path, PASSWORD)
    app = create_app(path)
    app.config["AUTH_FAIL_DELAY"] = 0
    return app.test_client(), path


def test_without_a_password_file_the_pages_are_open(tmp_path):
    assert create_app(tmp_path / "open.db").test_client().get("/").status_code == 200


def test_requests_without_credentials_get_401_and_a_challenge(protected):
    client, _ = protected
    response = client.get("/")
    assert response.status_code == 401
    assert "Basic" in response.headers["WWW-Authenticate"]


@pytest.mark.parametrize("user,password", [("admin", "wrong"), ("root", PASSWORD), ("admin", "")])
def test_wrong_credentials_get_401(protected, user, password):
    client, _ = protected
    assert client.get("/", headers=basic(user, password)).status_code == 401


def test_right_credentials_open_every_page(protected):
    client, _ = protected
    headers = basic("admin", PASSWORD)
    for url in ("/", "/groups", "/differences", "/static/style.css"):
        assert client.get(url, headers=headers).status_code == 200, url


def test_post_is_protected_too(protected):
    client, _ = protected
    assert client.post("/groups", data={"csrf_token": "x"}).status_code == 401


def test_security_headers_are_set(protected):
    client, _ = protected
    response = client.get("/", headers=basic("admin", PASSWORD))
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/").headers["X-Frame-Options"] == "DENY"


def test_password_file_is_private_and_holds_no_clear_text(protected):
    _, path = protected
    file = auth.password_file(path)
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert PASSWORD not in file.read_text()


def test_short_password_is_refused(tmp_path):
    with pytest.raises(ValueError):
        auth.set_password(tmp_path / "x.db", "short")


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("192.0.2.5", False),
    ],
)
def test_is_loopback(host, expected):
    assert auth.is_loopback(host) is expected


def test_serve_refuses_a_network_address_without_a_password(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "s.db"))
    assert main(["serve", "--host", "0.0.0.0"]) == 1
    assert "set-password" in capsys.readouterr().err
