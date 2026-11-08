"""Flask application: server-rendered pages."""

import sqlite3
from pathlib import Path

from flask import Flask, g, render_template, request

from network_inventory import db, inventory

# How the device list can be organised: key -> label.
VIEWS = {
    "group": "Group",
    "type": "Type",
    "category": "Category",
    "ip": "IP",
    "name": "Name",
}


def create_app(db_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path or db.db_path())

    def get_conn() -> sqlite3.Connection:
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(_error):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.get("/")
    def index():
        conn = get_conn()
        view = request.args.get("by", "group")
        if view not in VIEWS:
            view = "group"
        groups = {grp.id: grp for grp in inventory.list_groups(conn)}
        sections = build_sections(inventory.list_devices(conn), groups, view)
        return render_template("index.html", sections=sections, view=view, views=VIEWS)

    return app


def _first_ip(device: inventory.Device) -> int:
    ips = [int(inventory.parse_ip(i.expected_ip)) for i in device.interfaces if i.expected_ip]
    return min(ips) if ips else 2**32


def build_sections(
    devices: list[inventory.Device], groups: dict[int, inventory.Group], view: str
) -> list[dict]:
    """Devices split into titled sections. Flat views have a single untitled section."""
    if view == "ip":
        return [{"title": "", "note": "", "devices": sorted(devices, key=_first_ip)}]
    if view == "name":
        return [{"title": "", "note": "", "devices": devices}]

    buckets: dict[str, list[inventory.Device]] = {}
    notes: dict[str, str] = {}
    order: list[str] = []
    ordered_groups = list(groups.values())
    if view == "group":
        for grp in ordered_groups:
            order.append(grp.name)
            buckets[grp.name] = []
            free = " (free range)" if grp.is_free else ""
            notes[grp.name] = f"{grp.first_ip} to {grp.last_ip}{free}"
        for device in devices:
            buckets[groups[device.group_id].name].append(device)
    else:
        for device in sorted(devices, key=lambda d: (getattr(d, view) or "~").lower()):
            key = getattr(device, view) or "Not set"
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(device)
    return [
        {"title": key, "note": notes.get(key, ""), "devices": sorted(buckets[key], key=_first_ip)}
        for key in order
    ]
