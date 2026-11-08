import argparse
import getpass
import sys

from network_inventory import db, inventory, scanner
from network_inventory.compare import Finding, Status, compare
from network_inventory.web import auth
from network_inventory.web.app import create_app

_LABELS = {
    Status.MATCHING: "ok",
    Status.IP_CHANGED: "ip changed",
    Status.IP_OUTSIDE_GROUP: "ip outside group",
    Status.MISSING: "missing",
    Status.UNKNOWN_MAC: "unknown mac",
    Status.NEW_DEVICE: "new device",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="network-inventory")
    sub = parser.add_subparsers(dest="command")
    scan = sub.add_parser("scan", help="scan the local network and store what is seen")
    scan.add_argument("--interface", help="network interface to scan")
    sub.add_parser("diff", help="compare the last scan with the inventory")
    sub.add_parser("export", help="print a table of MAC, IP, name and group")
    sub.add_parser("set-password", help="set the password of the web interface")
    serve = sub.add_parser("serve", help="start the web interface")
    serve.add_argument("--host", default="127.0.0.1", help="address to listen on")
    serve.add_argument("--port", type=int, default=8080)
    return parser


def format_finding(finding: Finding) -> str:
    label = _LABELS[finding.status]
    obs = finding.observation
    if finding.device is not None:
        iface = finding.interface
        seen = f" seen {obs.ip}" if obs else ""
        return f"{label:<17} {finding.device.name}  {iface.mac} expected {iface.expected_ip}{seen}"
    names = ", ".join(d.name for d in finding.candidates[:3])
    hint = f"  could be: {names}" if names else ""
    return f"{label:<17} {obs.mac}  {obs.ip}  {obs.vendor}{hint}"


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        output = scanner.run_arp_scan(args.interface)
    except scanner.ScanError as error:
        print(f"Scan failed: {error}", file=sys.stderr)
        return 1
    conn = db.connect(db.db_path())
    observations = scanner.parse_arp_scan(output)
    scanner.store_observations(conn, observations)
    print(f"{len(observations)} device(s) seen.")
    return 0


def cmd_diff(_args: argparse.Namespace) -> int:
    conn = db.connect(db.db_path())
    observations = scanner.latest_scan(conn)
    if not observations:
        print("No scan yet: run `network-inventory scan` first.", file=sys.stderr)
        return 1
    findings = compare(inventory.list_devices(conn), inventory.list_groups(conn), observations)
    problems = [f for f in findings if f.status is not Status.MATCHING]
    for finding in problems:
        print(format_finding(finding))
    print(f"{len(findings) - len(problems)} ok, {len(problems)} to look at.")
    return 0


def cmd_export(_args: argparse.Namespace) -> int:
    conn = db.connect(db.db_path())
    groups = {g.id: g.name for g in inventory.list_groups(conn)}
    rows = [
        (i.mac, i.expected_ip or "", d.name, groups[d.group_id])
        for d in inventory.list_devices(conn)
        for i in d.interfaces
    ]
    rows.sort(key=lambda r: (int(inventory.parse_ip(r[1])) if r[1] else 2**32, r[0]))
    print("\t".join(("MAC", "IP", "NAME", "GROUP")))
    for row in rows:
        print("\t".join(row))
    return 0


def cmd_set_password(_args: argparse.Namespace) -> int:
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat the password: "):
        print("The passwords differ.", file=sys.stderr)
        return 1
    try:
        auth.set_password(db.db_path(), password)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Password saved. The user name is {auth.USERNAME!r}.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    path = db.db_path()
    if auth.load_hash(path) is None:
        if not auth.is_loopback(args.host):
            print(
                "Refusing to listen on a network address without a password: "
                "run `network-inventory set-password` first.",
                file=sys.stderr,
            )
            return 1
        print("Warning: no password set, open to this machine only.", file=sys.stderr)
    create_app(path).run(host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "scan": cmd_scan,
        "diff": cmd_diff,
        "export": cmd_export,
        "serve": cmd_serve,
        "set-password": cmd_set_password,
    }
    if args.command is None:
        parser.print_help()
        return 0
    return commands[args.command](args)
