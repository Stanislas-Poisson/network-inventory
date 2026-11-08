"""Inventory rules: devices, interfaces and groups, with validation.

A group is a name and an IP range. A device belongs to exactly one group, and every
expected IP of its interfaces lies inside the range of that group. Group ranges do not
overlap. Functions raise ``ValidationError`` with a message fit to show in a form.
"""

import ipaddress
import re
import sqlite3
from dataclasses import dataclass, field

_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


class ValidationError(ValueError):
    """The requested change breaks an inventory rule."""


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    first_ip: str
    last_ip: str
    is_free: bool


@dataclass(frozen=True)
class Interface:
    id: int
    device_id: int
    mac: str
    expected_ip: str | None
    label: str


@dataclass(frozen=True)
class Device:
    id: int
    name: str
    type: str
    group_id: int
    notes: str
    interfaces: list[Interface] = field(default_factory=list)


def normalize_mac(value: str) -> str:
    """Lowercase, colon separated MAC address, accepting ``-`` and ``.`` separators."""
    cleaned = re.sub(r"[-.]", ":", value.strip().lower())
    if not _MAC.match(cleaned):
        raise ValidationError(f"Invalid MAC address: {value!r}.")
    return cleaned


def parse_ip(value: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(value.strip())
    except ValueError:
        raise ValidationError(f"Invalid IPv4 address: {value!r}.") from None


def _clean_name(value: str, what: str) -> str:
    name = value.strip()
    if not name:
        raise ValidationError(f"The {what} name is required.")
    return name


# ---------------------------------------------------------------- groups


def _group(row: sqlite3.Row) -> Group:
    return Group(row["id"], row["name"], row["first_ip"], row["last_ip"], bool(row["is_free"]))


def get_group(conn: sqlite3.Connection, group_id: int) -> Group:
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        raise ValidationError("This group does not exist.")
    return _group(row)


def list_groups(conn: sqlite3.Connection) -> list[Group]:
    rows = conn.execute("SELECT * FROM groups ORDER BY first_ip").fetchall()
    return sorted((_group(r) for r in rows), key=lambda g: int(parse_ip(g.first_ip)))


def _check_range(conn: sqlite3.Connection, first: str, last: str, own_id: int | None) -> None:
    low, high = parse_ip(first), parse_ip(last)
    if low > high:
        raise ValidationError("The first IP of a group cannot be after its last IP.")
    for other in list_groups(conn):
        if other.id == own_id:
            continue
        if low <= parse_ip(other.last_ip) and parse_ip(other.first_ip) <= high:
            raise ValidationError(f"The range overlaps the group {other.name!r}.")


def _check_devices_fit(conn: sqlite3.Connection, group_id: int, first: str, last: str) -> None:
    low, high = parse_ip(first), parse_ip(last)
    rows = conn.execute(
        "SELECT d.name, i.expected_ip FROM interfaces i JOIN devices d ON d.id = i.device_id"
        " WHERE d.group_id = ? AND i.expected_ip IS NOT NULL",
        (group_id,),
    ).fetchall()
    for row in rows:
        if not low <= parse_ip(row["expected_ip"]) <= high:
            raise ValidationError(
                f"The device {row['name']!r} has {row['expected_ip']}, outside the new range."
            )


def create_group(
    conn: sqlite3.Connection, name: str, first_ip: str, last_ip: str, is_free: bool = False
) -> int:
    name = _clean_name(name, "group")
    first_ip, last_ip = str(parse_ip(first_ip)), str(parse_ip(last_ip))
    _check_range(conn, first_ip, last_ip, None)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO groups (name, first_ip, last_ip, is_free) VALUES (?, ?, ?, ?)",
                (name, first_ip, last_ip, int(is_free)),
            )
    except sqlite3.IntegrityError:
        raise ValidationError(f"A group named {name!r} already exists.") from None
    return cur.lastrowid


def update_group(
    conn: sqlite3.Connection,
    group_id: int,
    name: str,
    first_ip: str,
    last_ip: str,
    is_free: bool = False,
) -> None:
    get_group(conn, group_id)
    name = _clean_name(name, "group")
    first_ip, last_ip = str(parse_ip(first_ip)), str(parse_ip(last_ip))
    _check_range(conn, first_ip, last_ip, group_id)
    _check_devices_fit(conn, group_id, first_ip, last_ip)
    try:
        with conn:
            conn.execute(
                "UPDATE groups SET name = ?, first_ip = ?, last_ip = ?, is_free = ? WHERE id = ?",
                (name, first_ip, last_ip, int(is_free), group_id),
            )
    except sqlite3.IntegrityError:
        raise ValidationError(f"A group named {name!r} already exists.") from None


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    group = get_group(conn, group_id)
    count = conn.execute("SELECT COUNT(*) FROM devices WHERE group_id = ?", (group_id,)).fetchone()[
        0
    ]
    if count:
        raise ValidationError(f"The group {group.name!r} still has {count} device(s).")
    with conn:
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))


# ---------------------------------------------------------------- devices


def _check_ip_in_group(group: Group, ip: str) -> None:
    if not parse_ip(group.first_ip) <= parse_ip(ip) <= parse_ip(group.last_ip):
        raise ValidationError(
            f"{ip} is outside the range of the group {group.name!r}"
            f" ({group.first_ip} to {group.last_ip})."
        )


def _clean_interface(group: Group, mac: str, expected_ip: str | None) -> tuple[str, str | None]:
    mac = normalize_mac(mac)
    ip = (expected_ip or "").strip() or None
    if ip is not None:
        ip = str(parse_ip(ip))
        _check_ip_in_group(group, ip)
    return mac, ip


def _insert_interface(
    conn: sqlite3.Connection, device_id: int, mac: str, ip: str | None, label: str
) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO interfaces (device_id, mac, expected_ip, label) VALUES (?, ?, ?, ?)",
            (device_id, mac, ip, label.strip()),
        )
    except sqlite3.IntegrityError:
        raise ValidationError(f"The MAC {mac} or the IP {ip} is already used.") from None
    return cur.lastrowid


def create_device(
    conn: sqlite3.Connection,
    name: str,
    group_id: int,
    interfaces: list[tuple[str, str | None]] = (),
    type: str = "",
    notes: str = "",
) -> int:
    """Create a device and its interfaces, given as (mac, expected_ip) pairs."""
    name = _clean_name(name, "device")
    group = get_group(conn, group_id)
    cleaned = [_clean_interface(group, mac, ip) for mac, ip in interfaces]
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO devices (name, type, group_id, notes) VALUES (?, ?, ?, ?)",
                (name, type.strip(), group_id, notes.strip()),
            )
            device_id = cur.lastrowid
            for mac, ip in cleaned:
                _insert_interface(conn, device_id, mac, ip, "")
    except sqlite3.IntegrityError:
        raise ValidationError(f"A device named {name!r} already exists.") from None
    return device_id


def update_device(
    conn: sqlite3.Connection,
    device_id: int,
    name: str,
    group_id: int,
    type: str = "",
    notes: str = "",
) -> None:
    get_device(conn, device_id)
    name = _clean_name(name, "device")
    group = get_group(conn, group_id)
    for row in conn.execute(
        "SELECT expected_ip FROM interfaces WHERE device_id = ? AND expected_ip IS NOT NULL",
        (device_id,),
    ):
        _check_ip_in_group(group, row["expected_ip"])
    try:
        with conn:
            conn.execute(
                "UPDATE devices SET name = ?, type = ?, group_id = ?, notes = ? WHERE id = ?",
                (name, type.strip(), group_id, notes.strip(), device_id),
            )
    except sqlite3.IntegrityError:
        raise ValidationError(f"A device named {name!r} already exists.") from None


def delete_device(conn: sqlite3.Connection, device_id: int) -> None:
    get_device(conn, device_id)
    with conn:
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))


def _device(conn: sqlite3.Connection, row: sqlite3.Row) -> Device:
    interfaces = [
        Interface(r["id"], r["device_id"], r["mac"], r["expected_ip"], r["label"])
        for r in conn.execute(
            "SELECT * FROM interfaces WHERE device_id = ? ORDER BY id", (row["id"],)
        )
    ]
    return Device(
        row["id"],
        row["name"],
        row["type"],
        row["group_id"],
        row["notes"],
        interfaces,
    )


def get_device(conn: sqlite3.Connection, device_id: int) -> Device:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if row is None:
        raise ValidationError("This device does not exist.")
    return _device(conn, row)


def list_types(conn: sqlite3.Connection) -> list[str]:
    """The distinct device types already used, to suggest them again."""
    rows = conn.execute(
        "SELECT DISTINCT type FROM devices WHERE type != '' ORDER BY type COLLATE NOCASE"
    ).fetchall()
    return [r["type"] for r in rows]


def list_devices(conn: sqlite3.Connection) -> list[Device]:
    rows = conn.execute("SELECT * FROM devices ORDER BY name COLLATE NOCASE").fetchall()
    return [_device(conn, r) for r in rows]


# ---------------------------------------------------------------- interfaces


def add_interface(
    conn: sqlite3.Connection,
    device_id: int,
    mac: str,
    expected_ip: str | None = None,
    label: str = "",
) -> int:
    """Add a network card to a device."""
    device = get_device(conn, device_id)
    mac, ip = _clean_interface(get_group(conn, device.group_id), mac, expected_ip)
    with conn:
        return _insert_interface(conn, device_id, mac, ip, label)


def update_interface(
    conn: sqlite3.Connection, interface_id: int, mac: str, expected_ip: str | None, label: str = ""
) -> None:
    row = conn.execute("SELECT * FROM interfaces WHERE id = ?", (interface_id,)).fetchone()
    if row is None:
        raise ValidationError("This interface does not exist.")
    device = get_device(conn, row["device_id"])
    mac, ip = _clean_interface(get_group(conn, device.group_id), mac, expected_ip)
    try:
        with conn:
            conn.execute(
                "UPDATE interfaces SET mac = ?, expected_ip = ?, label = ? WHERE id = ?",
                (mac, ip, label.strip(), interface_id),
            )
    except sqlite3.IntegrityError:
        raise ValidationError(f"The MAC {mac} or the IP {ip} is already used.") from None


def delete_interface(conn: sqlite3.Connection, interface_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM interfaces WHERE id = ?", (interface_id,))


# ---------------------------------------------------------------- allocation


def next_free_ip(conn: sqlite3.Connection, group_id: int) -> str | None:
    """The first IP of the group that no interface expects, or None when it is full."""
    group = get_group(conn, group_id)
    used = {
        row["expected_ip"]
        for row in conn.execute("SELECT expected_ip FROM interfaces WHERE expected_ip IS NOT NULL")
    }
    low, high = int(parse_ip(group.first_ip)), int(parse_ip(group.last_ip))
    for value in range(low, high + 1):
        candidate = str(ipaddress.IPv4Address(value))
        if candidate not in used:
            return candidate
    return None
