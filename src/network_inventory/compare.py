"""Compare the inventory with the observations of a scan.

Pure function: no network, no database, no web. Callers pass what they loaded.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from network_inventory.inventory import Device, Group, Interface
from network_inventory.scanner import Observation


class Status(StrEnum):
    MATCHING = "matching"
    IP_CHANGED = "ip-changed"
    IP_OUTSIDE_GROUP = "ip-outside-group"
    MISSING = "missing"
    UNKNOWN_MAC = "unknown-mac"
    NEW_DEVICE = "new-device"


@dataclass(frozen=True)
class Finding:
    status: Status
    device: Device | None = None
    interface: Interface | None = None
    observation: Observation | None = None
    # For an unknown MAC or a new device: devices that are absent and could be this one.
    candidates: list[Device] = field(default_factory=list)


def _in_group(group: Group | None, ip: str) -> bool:
    return group is not None and group.contains(ip)


def _group_of(groups: dict[int, Group], ip: str) -> Group | None:
    return next((g for g in groups.values() if _in_group(g, ip)), None)


def compare(
    devices: list[Device], groups: list[Group], observations: list[Observation]
) -> list[Finding]:
    """One finding per inventory interface, then one per observed MAC nobody owns."""
    by_group = {g.id: g for g in groups}
    seen = {o.mac: o for o in observations}
    known_macs = {i.mac for d in devices for i in d.interfaces}

    findings: list[Finding] = []
    absent: list[Device] = []
    for device in devices:
        device_seen = False
        for interface in device.interfaces:
            obs = seen.get(interface.mac)
            if obs is None:
                findings.append(Finding(Status.MISSING, device, interface))
                continue
            device_seen = True
            group = by_group.get(device.group_id)
            if interface.expected_ip in (None, obs.ip):
                status = Status.MATCHING
            elif not _in_group(group, obs.ip):
                status = Status.IP_OUTSIDE_GROUP
            else:
                status = Status.IP_CHANGED
            findings.append(Finding(status, device, interface, obs))
        if device.interfaces and not device_seen:
            absent.append(device)

    for obs in observations:
        if obs.mac in known_macs:
            continue
        group = _group_of(by_group, obs.ip)
        status = Status.NEW_DEVICE if group is not None and group.is_free else Status.UNKNOWN_MAC
        # Absent devices first whose group holds the observed IP.
        candidates = sorted(absent, key=lambda d: not _in_group(by_group.get(d.group_id), obs.ip))
        findings.append(Finding(status, None, None, obs, candidates))
    return findings
