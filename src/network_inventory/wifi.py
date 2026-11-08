"""Wi-Fi networks and the QR code that makes joining one easy.

The key is stored in clear: the QR code needs it. It is only shown on request, never
logged, and the QR code is built here, never by an external service.
"""

import io
import re
import sqlite3
from dataclasses import dataclass

import segno

from network_inventory.inventory import ValidationError

SECURITIES = {"WPA": "WPA / WPA2 / WPA3", "WEP": "WEP", "nopass": "Open (no key)"}

_SPECIAL = re.compile(r'([\\;,:"])')
_HEX = re.compile(r"^[0-9a-fA-F]+$")


@dataclass(frozen=True)
class WifiNetwork:
    id: int
    ssid: str
    password: str
    security: str
    hidden: bool
    notes: str

    def __repr__(self) -> str:
        # Never let the key reach a log or a traceback.
        return f"WifiNetwork(id={self.id}, ssid={self.ssid!r}, security={self.security!r})"


def _escape(value: str) -> str:
    """Escape the characters that are special in the QR payload; quote a pure hex value."""
    escaped = _SPECIAL.sub(r"\\\1", value)
    return f'"{escaped}"' if _HEX.match(value) else escaped


def payload(network: WifiNetwork) -> str:
    """The standard ``WIFI:T:WPA;S:ssid;P:key;H:true;;`` string read by phone cameras."""
    parts = [f"T:{network.security}", f"S:{_escape(network.ssid)}"]
    if network.security != "nopass":
        parts.append(f"P:{_escape(network.password)}")
    if network.hidden:
        parts.append("H:true")
    return "WIFI:" + ";".join(parts) + ";;"


def qr_svg(network: WifiNetwork) -> str:
    """The QR code as an SVG document."""
    code = segno.make(payload(network), error="m", micro=False)
    out = io.BytesIO()
    # A standalone file: it needs the XML declaration and the SVG namespace, or a browser
    # refuses to show it in an <img>. (svg_inline leaves both out, it is for HTML pages.)
    code.save(
        out, kind="svg", scale=8, border=4, dark="#000", light="#fff", xmldecl=True, svgns=True
    )
    return out.getvalue().decode("utf-8")


def _validate(ssid: str, password: str, security: str) -> tuple[str, str]:
    ssid = ssid.strip()
    if security not in SECURITIES:
        raise ValidationError("Choose a security type.")
    if not 1 <= len(ssid.encode()) <= 32:
        raise ValidationError("The network name (SSID) must be 1 to 32 bytes long.")
    if security == "nopass":
        return ssid, ""
    wpa_ok = 8 <= len(password) <= 63 or re.fullmatch(r"[0-9a-fA-F]{64}", password)
    if security == "WPA" and not wpa_ok:
        raise ValidationError("A WPA key is 8 to 63 characters (or 64 hexadecimal digits).")
    if security == "WEP" and not password:
        raise ValidationError("A WEP key is required.")
    return ssid, password


def _network(row: sqlite3.Row) -> WifiNetwork:
    return WifiNetwork(
        row["id"], row["ssid"], row["password"], row["security"], bool(row["hidden"]), row["notes"]
    )


def list_networks(conn: sqlite3.Connection) -> list[WifiNetwork]:
    rows = conn.execute("SELECT * FROM wifi_networks ORDER BY ssid COLLATE NOCASE").fetchall()
    return [_network(r) for r in rows]


def get_network(conn: sqlite3.Connection, network_id: int) -> WifiNetwork:
    row = conn.execute("SELECT * FROM wifi_networks WHERE id = ?", (network_id,)).fetchone()
    if row is None:
        raise ValidationError("This Wi-Fi network does not exist.")
    return _network(row)


def create_network(
    conn: sqlite3.Connection,
    ssid: str,
    password: str,
    security: str,
    hidden: bool = False,
    notes: str = "",
) -> int:
    ssid, password = _validate(ssid, password, security)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO wifi_networks (ssid, password, security, hidden, notes)"
                " VALUES (?, ?, ?, ?, ?)",
                (ssid, password, security, int(hidden), notes.strip()),
            )
    except sqlite3.IntegrityError:
        raise ValidationError(f"A network named {ssid!r} already exists.") from None
    return cur.lastrowid


def update_network(
    conn: sqlite3.Connection,
    network_id: int,
    ssid: str,
    password: str | None,
    security: str,
    hidden: bool = False,
    notes: str = "",
) -> None:
    """Update a network. ``password=None`` or an empty string keeps the current key."""
    current = get_network(conn, network_id)
    key = password if password else current.password
    ssid, key = _validate(ssid, key, security)
    try:
        with conn:
            conn.execute(
                "UPDATE wifi_networks SET ssid = ?, password = ?, security = ?, hidden = ?,"
                " notes = ? WHERE id = ?",
                (ssid, key, security, int(hidden), notes.strip(), network_id),
            )
    except sqlite3.IntegrityError:
        raise ValidationError(f"A network named {ssid!r} already exists.") from None


def delete_network(conn: sqlite3.Connection, network_id: int) -> None:
    get_network(conn, network_id)
    with conn:
        conn.execute("DELETE FROM wifi_networks WHERE id = ?", (network_id,))
