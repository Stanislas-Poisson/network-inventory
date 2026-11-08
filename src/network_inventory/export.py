"""Exports: the router table, and the full JSON backup that can be imported again.

The backup holds the Wi-Fi keys in clear (the file is meant to be stored encrypted).
"""

import csv
import io
import json
import sqlite3

from network_inventory import db, inventory, wifi
from network_inventory.inventory import ValidationError

BACKUP_VERSION = 1
ROUTER_HEADER = ("MAC", "IP", "NAME", "GROUP")


def router_rows(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    """One row per network interface, sorted by IP (interfaces without an IP last)."""
    groups = {g.id: g.name for g in inventory.list_groups(conn)}
    rows = [
        (i.mac, i.expected_ip or "", d.name, groups[d.group_id])
        for d in inventory.list_devices(conn)
        for i in d.interfaces
    ]
    rows.sort(key=lambda r: (int(inventory.parse_ip(r[1])) if r[1] else 2**32, r[0]))
    return rows


def to_text(rows) -> str:
    return "\n".join("\t".join(row) for row in (ROUTER_HEADER, *rows)) + "\n"


def to_csv(rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(ROUTER_HEADER)
    writer.writerows(rows)
    return out.getvalue()


def to_markdown(rows) -> str:
    def cell(value: str) -> str:
        return value.replace("|", "\\|")

    lines = ["| " + " | ".join(ROUTER_HEADER) + " |", "| --- | --- | --- | --- |"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def backup(conn: sqlite3.Connection, include_wifi_keys: bool = True) -> dict:
    groups = inventory.list_groups(conn)
    names = {g.id: g.name for g in groups}
    return {
        "version": BACKUP_VERSION,
        "groups": [
            {"name": g.name, "first_ip": g.first_ip, "last_ip": g.last_ip, "is_free": g.is_free}
            for g in groups
        ],
        "devices": [
            {
                "name": d.name,
                "group": names[d.group_id],
                "type": d.type,
                "notes": d.notes,
                "interfaces": [
                    {"mac": i.mac, "ip": i.expected_ip, "label": i.label} for i in d.interfaces
                ],
            }
            for d in inventory.list_devices(conn)
        ],
        "wifi_networks": [
            {
                "ssid": n.ssid,
                "security": n.security,
                "hidden": n.hidden,
                "notes": n.notes,
                **({"password": n.password} if include_wifi_keys else {}),
            }
            for n in wifi.list_networks(conn)
        ],
    }


def to_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _is_empty(conn: sqlite3.Connection) -> bool:
    for table in ("groups", "devices", "wifi_networks"):
        if conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:  # noqa: S608
            return False
    return True


def _load(conn: sqlite3.Connection, data: dict) -> None:
    if data.get("version") != BACKUP_VERSION:
        raise ValidationError(f"Unsupported backup version: {data.get('version')!r}.")
    ids = {}
    for g in data.get("groups", []):
        ids[g["name"]] = inventory.create_group(
            conn, g["name"], g["first_ip"], g["last_ip"], bool(g.get("is_free"))
        )
    for d in data.get("devices", []):
        if d["group"] not in ids:
            raise ValidationError(f"The device {d['name']!r} uses an unknown group.")
        device_id = inventory.create_device(
            conn,
            d["name"],
            ids[d["group"]],
            [(i["mac"], i.get("ip")) for i in d.get("interfaces", [])],
            d.get("type", ""),
            d.get("notes", ""),
        )
        for stored, item in zip(
            inventory.get_device(conn, device_id).interfaces, d.get("interfaces", []), strict=True
        ):
            if item.get("label"):
                inventory.update_interface(
                    conn, stored.id, stored.mac, stored.expected_ip, item["label"]
                )
    for n in data.get("wifi_networks", []):
        wifi.create_network(
            conn,
            n["ssid"],
            n.get("password", ""),
            n["security"],
            bool(n.get("hidden")),
            n.get("notes", ""),
        )


def restore(conn: sqlite3.Connection, data: dict) -> None:
    """Import a backup into an empty inventory. Nothing is saved when anything is wrong."""
    if not _is_empty(conn):
        raise ValidationError("The inventory is not empty: import into a new database.")
    # Dry run on a throwaway database, so a bad file leaves the real one untouched.
    _load(db.connect(":memory:"), data)
    _load(conn, data)
