import pytest

from network_inventory import db, inventory
from network_inventory.inventory import ValidationError


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.fixture
def pc_group(conn):
    return inventory.create_group(conn, "PC", "192.0.2.10", "192.0.2.19")


def test_normalize_mac_accepts_common_separators():
    assert inventory.normalize_mac("AA-BB-CC-00-11-22") == "aa:bb:cc:00:11:22"


@pytest.mark.parametrize("bad", ["", "aa:bb", "zz:bb:cc:00:11:22", "aa:bb:cc:00:11:22:33"])
def test_normalize_mac_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        inventory.normalize_mac(bad)


def test_group_rejects_reversed_range(conn):
    with pytest.raises(ValidationError):
        inventory.create_group(conn, "X", "192.0.2.20", "192.0.2.10")


def test_group_rejects_overlap_but_allows_adjacent(conn, pc_group):
    with pytest.raises(ValidationError, match="overlaps"):
        inventory.create_group(conn, "Other", "192.0.2.19", "192.0.2.29")
    inventory.create_group(conn, "Other", "192.0.2.20", "192.0.2.29")


def test_group_name_is_unique(conn, pc_group):
    with pytest.raises(ValidationError, match="already exists"):
        inventory.create_group(conn, "PC", "192.0.2.50", "192.0.2.59")


def test_device_with_interfaces(conn, pc_group):
    device_id = inventory.create_device(
        conn,
        "Desktop",
        pc_group,
        [("AA:BB:CC:00:11:22", "192.0.2.10"), ("aa:bb:cc:00:11:23", "192.0.2.11")],
        type="computer",
    )
    device = inventory.get_device(conn, device_id)
    assert device.name == "Desktop"
    assert [i.expected_ip for i in device.interfaces] == ["192.0.2.10", "192.0.2.11"]


def test_ip_outside_the_group_is_refused_and_nothing_is_saved(conn, pc_group):
    with pytest.raises(ValidationError, match="outside the range"):
        inventory.create_device(conn, "Desktop", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.30")])
    assert inventory.list_devices(conn) == []


def test_duplicate_mac_or_ip_is_refused(conn, pc_group):
    inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.10")])
    with pytest.raises(ValidationError):
        inventory.create_device(conn, "B", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.11")])
    with pytest.raises(ValidationError):
        inventory.create_device(conn, "C", pc_group, [("aa:bb:cc:00:11:33", "192.0.2.10")])
    assert [d.name for d in inventory.list_devices(conn)] == ["A"]


def test_device_name_is_unique(conn, pc_group):
    inventory.create_device(conn, "A", pc_group)
    with pytest.raises(ValidationError, match="already exists"):
        inventory.create_device(conn, "A", pc_group)


def test_new_network_card_is_an_extra_interface(conn, pc_group):
    device_id = inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.10")])
    inventory.add_interface(conn, device_id, "aa:bb:cc:00:11:99", "192.0.2.12", "usb")
    assert len(inventory.get_device(conn, device_id).interfaces) == 2


def test_moving_a_device_checks_its_ips(conn, pc_group):
    other = inventory.create_group(conn, "Other", "192.0.2.20", "192.0.2.29")
    device_id = inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.10")])
    with pytest.raises(ValidationError, match="outside the range"):
        inventory.update_device(conn, device_id, "A", other)


def test_shrinking_a_group_checks_its_devices(conn, pc_group):
    inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.18")])
    with pytest.raises(ValidationError, match="outside the new range"):
        inventory.update_group(conn, pc_group, "PC", "192.0.2.10", "192.0.2.15")


def test_group_with_devices_cannot_be_deleted(conn, pc_group):
    inventory.create_device(conn, "A", pc_group)
    with pytest.raises(ValidationError, match="still has"):
        inventory.delete_group(conn, pc_group)


def test_deleting_a_device_deletes_its_interfaces(conn, pc_group):
    device_id = inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", None)])
    inventory.delete_device(conn, device_id)
    assert conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0] == 0
