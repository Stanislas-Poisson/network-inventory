"""ARP scanner: run ``arp-scan``, parse its output and store the observations.

The scan needs to see the local network and the ``cap_net_raw`` capability on
``arp-scan``: the application itself never runs as root.
"""

import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from network_inventory.inventory import normalize_mac, parse_ip

_DUP = re.compile(r"\s*\(DUP: \d+\)\s*$")


class ScanError(RuntimeError):
    """The scan could not run."""


@dataclass(frozen=True)
class Observation:
    mac: str
    ip: str
    vendor: str
    last_seen: str = ""


def parse_arp_scan(output: str) -> list[Observation]:
    """Parse the tab separated lines ``IP  MAC  vendor``. Other lines are ignored.

    A MAC answered twice (``DUP`` lines) is kept once.
    """
    found: dict[str, Observation] = {}
    for line in output.splitlines():
        parts = line.rstrip("\n").split("\t", 2)
        if len(parts) < 2:
            continue
        try:
            ip = str(parse_ip(parts[0]))
            mac = normalize_mac(parts[1])
        except ValueError:
            continue
        vendor = _DUP.sub("", parts[2]).strip() if len(parts) > 2 else ""
        found.setdefault(mac, Observation(mac, ip, vendor))
    return list(found.values())


def run_arp_scan(interface: str | None = None) -> str:
    """Run ``arp-scan --localnet`` and return its output."""
    binary = shutil.which("arp-scan") or shutil.which("arp-scan", path="/usr/sbin:/sbin")
    if binary is None:
        raise ScanError("arp-scan is not installed.")
    command = [binary, "--localnet", "--plain", "--retry=2"]
    if interface:
        command.append(f"--interface={interface}")
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise ScanError(result.stderr.strip() or "arp-scan failed (missing capability?).")
    return result.stdout


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_observations(
    conn: sqlite3.Connection, observations: list[Observation], seen_at: str | None = None
) -> str:
    """Record a scan. Every observation of one scan gets the same ``last_seen``."""
    seen_at = seen_at or now_utc()
    with conn:
        for obs in observations:
            conn.execute(
                "INSERT INTO observations (mac, ip, vendor, first_seen, last_seen)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (mac) DO UPDATE SET"
                " ip = excluded.ip, vendor = excluded.vendor, last_seen = excluded.last_seen",
                (obs.mac, obs.ip, obs.vendor, seen_at, seen_at),
            )
    return seen_at


def latest_scan(conn: sqlite3.Connection) -> list[Observation]:
    """The observations of the most recent scan (those sharing the newest ``last_seen``)."""
    rows = conn.execute(
        "SELECT * FROM observations WHERE last_seen = (SELECT MAX(last_seen) FROM observations)"
        " ORDER BY ip"
    ).fetchall()
    rows.sort(key=lambda r: int(parse_ip(r["ip"])))
    return [Observation(r["mac"], r["ip"], r["vendor"], r["last_seen"]) for r in rows]
