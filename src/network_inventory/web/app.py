"""Flask application: server-rendered pages."""

import hmac
import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

from network_inventory import db, inventory
from network_inventory.inventory import ValidationError

# How the device list can be organised: key -> label.
VIEWS = {
    "group": "Group",
    "type": "Type",
    "category": "Category",
    "ip": "IP",
    "name": "Name",
}


def load_secret_key(db_file: Path) -> bytes:
    """The key that signs the session, kept in a file next to the database (mode 600)."""
    path = db_file.with_name(db_file.name + ".secret")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(secrets.token_bytes(32))
    return path.read_bytes()


def create_app(db_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path or db.db_path())
    app.secret_key = load_secret_key(Path(app.config["DB_PATH"]))
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token", "")
            if not hmac.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Invalid or missing CSRF token.")

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

    register_edit_routes(app, get_conn)
    return app


def _field(name: str) -> str:
    return request.form.get(name, "").strip()


def register_edit_routes(app: Flask, get_conn) -> None:
    def groups_page(error: str | None = None, form: dict | None = None, status: int = 200):
        conn = get_conn()
        return (
            render_template(
                "groups.html",
                groups=inventory.list_groups(conn),
                error=error,
                form=form or {},
            ),
            status,
        )

    @app.get("/groups")
    def groups():
        return groups_page()

    @app.post("/groups")
    def group_create():
        form = {k: _field(k) for k in ("name", "first_ip", "last_ip")}
        form["is_free"] = "is_free" in request.form
        try:
            inventory.create_group(get_conn(), **form)
        except ValidationError as error:
            return groups_page(str(error), form, 400)
        flash("Group created.")
        return redirect(url_for("groups"))

    @app.route("/groups/<int:group_id>", methods=["GET", "POST"])
    def group_edit(group_id: int):
        conn = get_conn()
        try:
            group = inventory.get_group(conn, group_id)
        except ValidationError:
            abort(404)
        error, status = None, 200
        form = {
            "name": group.name,
            "first_ip": group.first_ip,
            "last_ip": group.last_ip,
            "is_free": group.is_free,
        }
        if request.method == "POST":
            form = {k: _field(k) for k in ("name", "first_ip", "last_ip")}
            form["is_free"] = "is_free" in request.form
            try:
                inventory.update_group(conn, group_id, **form)
            except ValidationError as err:
                error, status = str(err), 400
            else:
                flash("Group saved.")
                return redirect(url_for("groups"))
        return render_template("group_edit.html", group=group, form=form, error=error), status

    @app.post("/groups/<int:group_id>/delete")
    def group_delete(group_id: int):
        try:
            inventory.delete_group(get_conn(), group_id)
        except ValidationError as error:
            flash(str(error))
        else:
            flash("Group deleted.")
        return redirect(url_for("groups"))

    def device_form_page(device, form, error, status):
        conn = get_conn()
        groups_ = inventory.list_groups(conn)
        group_id = form.get("group_id") or (groups_[0].id if groups_ else None)
        suggestion = None
        if group_id:
            try:
                suggestion = inventory.next_free_ip(conn, int(group_id))
            except (ValidationError, ValueError):
                suggestion = None
        return (
            render_template(
                "device_form.html",
                device=device,
                groups=groups_,
                form=form,
                error=error,
                suggestion=suggestion,
            ),
            status,
        )

    @app.route("/devices/new", methods=["GET", "POST"])
    def device_new():
        form = {"group_id": request.args.get("group", "")}
        if request.method == "POST":
            form = {k: _field(k) for k in ("name", "type", "category", "notes", "mac", "ip")}
            form["group_id"] = _field("group_id")
            try:
                interfaces = [(form["mac"], form["ip"])] if form["mac"] else []
                device_id = inventory.create_device(
                    get_conn(),
                    form["name"],
                    int(form["group_id"] or 0),
                    interfaces,
                    form["type"],
                    form["category"],
                    form["notes"],
                )
            except ValidationError as error:
                return device_form_page(None, form, str(error), 400)
            flash("Device created.")
            return redirect(url_for("device_edit", device_id=device_id))
        return device_form_page(None, form, None, 200)

    @app.route("/devices/<int:device_id>", methods=["GET", "POST"])
    def device_edit(device_id: int):
        conn = get_conn()
        try:
            device = inventory.get_device(conn, device_id)
        except ValidationError:
            abort(404)
        form = {
            "name": device.name,
            "type": device.type,
            "category": device.category,
            "notes": device.notes,
            "group_id": str(device.group_id),
        }
        if request.method == "POST":
            form = {k: _field(k) for k in ("name", "type", "category", "notes", "group_id")}
            try:
                inventory.update_device(
                    conn,
                    device_id,
                    form["name"],
                    int(form["group_id"] or 0),
                    form["type"],
                    form["category"],
                    form["notes"],
                )
            except ValidationError as error:
                return device_form_page(device, form, str(error), 400)
            flash("Device saved.")
            return redirect(url_for("device_edit", device_id=device_id))
        return device_form_page(device, form, None, 200)

    @app.post("/devices/<int:device_id>/delete")
    def device_delete(device_id: int):
        try:
            inventory.delete_device(get_conn(), device_id)
        except ValidationError:
            abort(404)
        flash("Device deleted.")
        return redirect(url_for("index"))

    @app.post("/devices/<int:device_id>/interfaces")
    def interface_add(device_id: int):
        try:
            inventory.add_interface(
                get_conn(), device_id, _field("mac"), _field("ip"), _field("label")
            )
        except ValidationError as error:
            flash(str(error))
        else:
            flash("Interface added.")
        return redirect(url_for("device_edit", device_id=device_id))

    @app.post("/interfaces/<int:interface_id>")
    def interface_save(interface_id: int):
        conn = get_conn()
        row = conn.execute(
            "SELECT device_id FROM interfaces WHERE id = ?", (interface_id,)
        ).fetchone()
        if row is None:
            abort(404)
        try:
            inventory.update_interface(
                conn, interface_id, _field("mac"), _field("ip"), _field("label")
            )
        except ValidationError as error:
            flash(str(error))
        else:
            flash("Interface saved.")
        return redirect(url_for("device_edit", device_id=row["device_id"]))

    @app.post("/interfaces/<int:interface_id>/delete")
    def interface_delete(interface_id: int):
        conn = get_conn()
        row = conn.execute(
            "SELECT device_id FROM interfaces WHERE id = ?", (interface_id,)
        ).fetchone()
        if row is None:
            abort(404)
        inventory.delete_interface(conn, interface_id)
        flash("Interface deleted.")
        return redirect(url_for("device_edit", device_id=row["device_id"]))


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
