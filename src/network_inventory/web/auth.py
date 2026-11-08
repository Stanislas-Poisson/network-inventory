"""Access control: one password (HTTP Basic), security headers, safe listening address."""

import ipaddress
import os
import time
from pathlib import Path

from flask import Flask, Response, request
from werkzeug.security import check_password_hash, generate_password_hash

USERNAME = "admin"
MIN_LENGTH = 12


def password_file(db_file: Path) -> Path:
    return db_file.with_name(db_file.name + ".password")


def set_password(db_file: Path, password: str) -> None:
    """Store the hash of the password in a file next to the database (mode 600)."""
    if len(password) < MIN_LENGTH:
        raise ValueError(f"The password needs at least {MIN_LENGTH} characters.")
    path = password_file(db_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(generate_password_hash(password))
    path.chmod(0o600)


def load_hash(db_file: Path) -> str | None:
    path = password_file(db_file)
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def install(app: Flask, db_file: Path) -> None:
    """Require the password on every request when one is set, and add the headers."""
    app.config.setdefault("AUTH_FAIL_DELAY", 0.5)
    password_hash = load_hash(db_file)

    @app.before_request
    def require_password():
        if password_hash is None:
            return None
        auth = request.authorization
        valid = auth is not None and auth.username == USERNAME
        if valid and check_password_hash(password_hash, auth.password or ""):
            return None
        if auth:
            time.sleep(app.config["AUTH_FAIL_DELAY"])
        return Response(
            "Authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Network inventory", charset="UTF-8"'},
        )

    @app.after_request
    def add_headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
