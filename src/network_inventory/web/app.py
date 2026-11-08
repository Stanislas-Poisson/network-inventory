"""Flask application: server-rendered pages."""

import hmac
import os
import secrets
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from network_inventory import db, export, inventory, scanner, wifi
from network_inventory.compare import Status, compare
from network_inventory.inventory import ValidationError
from network_inventory.web import auth

# How the device list can be organised: key -> label.
VIEWS = {
    "group": "Group",
    "type": "Type",
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
    auth.install(app, Path(app.config["DB_PATH"]))

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
    register_difference_routes(app, get_conn)
    register_wifi_routes(app, get_conn)
    register_export_routes(app, get_conn)
    return app


def _field(name: str) -> str:
    return request.form.get(name, "").strip()


def network_prefix(conn) -> str | None:
    """The network the groups live in: the setting, else the one this machine scanned."""
    saved = inventory.get_setting(conn, "network")
    if saved:
        return saved
    for obs in scanner.latest_scan(conn):
        if obs.vendor == scanner.SELF_VENDOR:
            return ".".join(obs.ip.split(".")[:3])
    return None


def group_values(prefix: str | None) -> dict:
    """The group fields of the posted form, as full IPs (octets are added to the prefix)."""
    form = {"name": _field("name"), "is_free": "is_free" in request.form}
    if "first_octet" in request.form and prefix:
        form["first_octet"], form["last_octet"] = _field("first_octet"), _field("last_octet")
    else:
        form["first_ip"], form["last_ip"] = _field("first_ip"), _field("last_ip")
    return form


def group_call_args(form: dict, prefix: str | None) -> dict:
    """The arguments of create_group and update_group for a posted form."""
    if "first_octet" in form:
        first = inventory.with_octet(prefix, form["first_octet"], "first")
        last = inventory.with_octet(prefix, form["last_octet"], "last")
    else:
        first, last = form["first_ip"], form["last_ip"]
    return {
        "name": form["name"],
        "first_ip": first,
        "last_ip": last,
        "is_free": form["is_free"],
    }


def register_edit_routes(app: Flask, get_conn) -> None:
    def groups_page(error: str | None = None, form: dict | None = None, status: int = 200):
        conn = get_conn()
        prefix = network_prefix(conn)
        return (
            render_template(
                "groups.html",
                groups=inventory.list_groups(conn),
                error=error,
                form=form or {},
                prefix=prefix,
                prefix_saved=inventory.get_setting(conn, "network"),
            ),
            status,
        )

    @app.post("/settings/network")
    def network_save():
        try:
            prefix = inventory.clean_prefix(request.form.get("prefix", ""))
        except ValidationError as error:
            flash(str(error))
        else:
            inventory.set_setting(get_conn(), "network", prefix)
            flash("Network saved.")
        return redirect(url_for("groups"))

    @app.get("/groups")
    def groups():
        return groups_page()

    @app.post("/groups")
    def group_create():
        conn = get_conn()
        prefix = network_prefix(conn)
        form = group_values(prefix)
        try:
            inventory.create_group(conn, **group_call_args(form, prefix))
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
        prefix = network_prefix(conn)
        # The octet inputs are only for a group that lives inside the network.
        inside = prefix and all(
            ip.startswith(prefix + ".") for ip in (group.first_ip, group.last_ip)
        )
        form = {"name": group.name, "is_free": group.is_free}
        if inside:
            form["first_octet"] = group.first_ip.rsplit(".", 1)[1]
            form["last_octet"] = group.last_ip.rsplit(".", 1)[1]
        else:
            form["first_ip"], form["last_ip"] = group.first_ip, group.last_ip
        if request.method == "POST":
            form = group_values(prefix if inside else None)
            try:
                inventory.update_group(conn, group_id, **group_call_args(form, prefix))
            except ValidationError as err:
                error, status = str(err), 400
            else:
                flash("Group saved.")
                return redirect(url_for("groups"))
        return (
            render_template(
                "group_edit.html",
                group=group,
                form=form,
                error=error,
                prefix=prefix if "first_octet" in form else None,
            ),
            status,
        )

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
                types=inventory.list_types(conn),
            ),
            status,
        )

    @app.route("/devices/new", methods=["GET", "POST"])
    def device_new():
        form = {
            "group_id": request.args.get("group", ""),
            "mac": request.args.get("mac", ""),
            "ip": request.args.get("ip", ""),
        }
        if request.method == "POST":
            form = {k: _field(k) for k in ("name", "type", "notes", "mac", "ip")}
            form["group_id"] = _field("group_id")
            try:
                interfaces = [(form["mac"], form["ip"])] if form["mac"] else []
                device_id = inventory.create_device(
                    get_conn(),
                    form["name"],
                    int(form["group_id"] or 0),
                    interfaces,
                    form["type"],
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
            "notes": device.notes,
            "group_id": str(device.group_id),
        }
        if request.method == "POST":
            form = {k: _field(k) for k in ("name", "type", "notes", "group_id")}
            try:
                inventory.update_device(
                    conn,
                    device_id,
                    form["name"],
                    int(form["group_id"] or 0),
                    form["type"],
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


def register_wifi_routes(app: Flask, get_conn) -> None:
    def fields() -> dict:
        form = {k: _field(k) for k in ("ssid", "security", "notes")}
        form["password"] = request.form.get("password", "")
        form["hidden"] = "hidden" in request.form
        return form

    def page(error=None, form=None, status=200):
        return (
            render_template(
                "wifi.html",
                networks=wifi.list_networks(get_conn()),
                securities=wifi.SECURITIES,
                error=error,
                form=form or {"security": "WPA"},
            ),
            status,
        )

    @app.get("/wifi")
    def wifi_list():
        return page()

    @app.post("/wifi")
    def wifi_create():
        form = fields()
        try:
            wifi.create_network(get_conn(), **form)
        except ValidationError as error:
            return page(str(error), form, 400)
        flash("Wi-Fi network created.")
        return redirect(url_for("wifi_list"))

    def network_or_404(network_id: int):
        try:
            return wifi.get_network(get_conn(), network_id)
        except ValidationError:
            abort(404)

    @app.route("/wifi/<int:network_id>", methods=["GET", "POST"])
    def wifi_edit(network_id: int):
        network = network_or_404(network_id)
        form = {
            "ssid": network.ssid,
            "security": network.security,
            "hidden": network.hidden,
            "notes": network.notes,
        }
        error, status = None, 200
        if request.method == "POST":
            form = fields()
            try:
                wifi.update_network(get_conn(), network_id, **form)
            except ValidationError as err:
                error, status = str(err), 400
            else:
                flash("Wi-Fi network saved.")
                return redirect(url_for("wifi_edit", network_id=network_id))
        return (
            render_template(
                "wifi_edit.html",
                network=network,
                securities=wifi.SECURITIES,
                form=form,
                error=error,
                # The key is only shown when asked for.
                reveal=request.args.get("reveal") == "1",
            ),
            status,
        )

    @app.post("/wifi/<int:network_id>/delete")
    def wifi_delete(network_id: int):
        network_or_404(network_id)
        wifi.delete_network(get_conn(), network_id)
        flash("Wi-Fi network deleted.")
        return redirect(url_for("wifi_list"))

    @app.get("/wifi/<int:network_id>/qr.svg")
    def wifi_qr(network_id: int):
        svg = wifi.qr_svg(network_or_404(network_id))
        return Response(svg, mimetype="image/svg+xml")

    @app.get("/wifi/<int:network_id>/qr")
    def wifi_qr_page(network_id: int):
        return render_template("wifi_qr.html", network=network_or_404(network_id))


def register_export_routes(app: Flask, get_conn) -> None:
    def download(text: str, name: str, mimetype: str) -> Response:
        response = Response(text, mimetype=mimetype)
        response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    @app.get("/export")
    def export_page():
        return render_template("export.html")

    @app.get("/export/router.csv")
    def export_csv():
        return download(export.to_csv(export.router_rows(get_conn())), "router.csv", "text/csv")

    @app.get("/export/router.md")
    def export_markdown():
        text = export.to_markdown(export.router_rows(get_conn()))
        return download(text, "router.md", "text/markdown")

    @app.get("/export/backup.json")
    def export_backup():
        keys = request.args.get("keys", "1") != "0"
        text = export.to_json(export.backup(get_conn(), include_wifi_keys=keys))
        return download(text, "network-inventory-backup.json", "application/json")


STATUS_LABELS = {
    Status.UNKNOWN_MAC: "Unknown MAC",
    Status.NEW_DEVICE: "New devices",
    Status.IP_OUTSIDE_GROUP: "IP outside the group",
    Status.IP_CHANGED: "IP changed",
    Status.MISSING: "Missing",
    Status.MATCHING: "Matching",
}


def register_difference_routes(app: Flask, get_conn) -> None:
    @app.get("/differences")
    def differences():
        conn = get_conn()
        observations = scanner.latest_scan(conn)
        devices = inventory.list_devices(conn)
        findings = compare(devices, inventory.list_groups(conn), observations)
        sections = []
        for status, label in STATUS_LABELS.items():
            matching = [f for f in findings if f.status == status]
            sections.append({"status": status, "title": label, "findings": matching})
        return render_template(
            "differences.html",
            sections=[sec for sec in sections if sec["findings"]],
            has_scan=bool(observations),
            scanned_at=observations[0].last_seen if observations else "",
            devices=devices,
            matching=Status.MATCHING,
        )

    @app.post("/scan")
    def scan():
        try:
            observations = scanner.parse_arp_scan(scanner.run_arp_scan())
        except scanner.ScanError as error:
            flash(f"Scan failed: {error}")
        else:
            scanner.store_observations(get_conn(), observations)
            flash(f"{len(observations)} device(s) seen.")
        return redirect(url_for("differences"))

    @app.post("/differences/attach")
    def attach():
        try:
            device_id = int(_field("device_id") or 0)
            inventory.add_interface(get_conn(), device_id, _field("mac"), _field("ip"))
        except (ValidationError, ValueError) as error:
            flash(str(error) if isinstance(error, ValidationError) else "Choose a device.")
            return redirect(url_for("differences"))
        flash("Network card attached.")
        return redirect(url_for("device_edit", device_id=device_id))


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
