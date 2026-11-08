import pytest

from network_inventory import db, inventory
from network_inventory.compare import Status, compare
from network_inventory.scanner import Observation


@pytest.fixture
def world():
    conn = db.connect(":memory:")
    pc = inventory.create_group(conn, "PC", "192.0.2.10", "192.0.2.19")
    iot = inventory.create_group(conn, "IoT", "192.0.2.40", "192.0.2.49")
    free = inventory.create_group(conn, "Free", "192.0.2.100", "192.0.2.199", is_free=True)
    inventory.create_device(conn, "Desktop", pc, [("aa:bb:cc:00:00:01", "192.0.2.10")])
    inventory.create_device(conn, "Lamp", iot, [("aa:bb:cc:00:00:02", "192.0.2.41")])
    inventory.create_device(conn, "Sensor", iot, [("aa:bb:cc:00:00:03", "192.0.2.42")])
    return conn, inventory.list_devices(conn), inventory.list_groups(conn), free


def obs(mac, ip):
    return Observation(mac, ip, "")


def statuses(findings):
    return {(f.device.name if f.device else f.observation.mac): f.status for f in findings}


def test_matching_and_missing(world):
    _, devices, groups, _ = world
    result = statuses(compare(devices, groups, [obs("aa:bb:cc:00:00:01", "192.0.2.10")]))
    assert result["Desktop"] == Status.MATCHING
    assert result["Lamp"] == Status.MISSING
    assert result["Sensor"] == Status.MISSING


def test_ip_changed_inside_the_group(world):
    _, devices, groups, _ = world
    found = statuses(compare(devices, groups, [obs("aa:bb:cc:00:00:02", "192.0.2.45")]))
    assert found["Lamp"] == Status.IP_CHANGED


def test_ip_outside_the_group(world):
    _, devices, groups, _ = world
    found = statuses(compare(devices, groups, [obs("aa:bb:cc:00:00:02", "192.0.2.150")]))
    assert found["Lamp"] == Status.IP_OUTSIDE_GROUP


def test_unknown_mac_outside_the_free_range(world):
    _, devices, groups, _ = world
    found = compare(devices, groups, [obs("de:ad:be:ef:00:01", "192.0.2.43")])
    unknown = next(f for f in found if f.observation and f.device is None)
    assert unknown.status == Status.UNKNOWN_MAC


def test_unknown_mac_in_the_free_range_is_a_new_device(world):
    _, devices, groups, _ = world
    found = compare(devices, groups, [obs("de:ad:be:ef:00:01", "192.0.2.120")])
    new = next(f for f in found if f.device is None)
    assert new.status == Status.NEW_DEVICE


def test_candidates_are_absent_devices_with_the_observed_ip_group_first(world):
    _, devices, groups, _ = world
    # Lamp and Sensor are absent (IoT), Desktop is present: the new MAC is at an IoT address.
    scan = [obs("aa:bb:cc:00:00:01", "192.0.2.10"), obs("de:ad:be:ef:00:01", "192.0.2.43")]
    unknown = next(f for f in compare(devices, groups, scan) if f.device is None)
    assert [d.name for d in unknown.candidates] == ["Lamp", "Sensor"]


def test_device_without_expected_ip_matches_wherever_it_is(world):
    conn, _, _, _ = world
    group = inventory.list_groups(conn)[0].id
    inventory.create_device(conn, "NoIp", group, [("aa:bb:cc:00:00:09", None)])
    found = statuses(
        compare(
            inventory.list_devices(conn),
            inventory.list_groups(conn),
            [obs("aa:bb:cc:00:00:09", "192.0.2.14")],
        )
    )
    assert found["NoIp"] == Status.MATCHING
