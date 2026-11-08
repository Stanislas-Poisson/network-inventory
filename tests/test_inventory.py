import pytest

from network_inventory import db, inventory
from network_inventory.inventory import ValidationError


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.fixture
def pc_group(conn):
    return inventory.create_group(conn, "PC", [("192.0.2.10", "192.0.2.19")])


def test_normalize_mac_accepts_common_separators():
    assert inventory.normalize_mac("AA-BB-CC-00-11-22") == "aa:bb:cc:00:11:22"


@pytest.mark.parametrize("bad", ["", "aa:bb", "zz:bb:cc:00:11:22", "aa:bb:cc:00:11:22:33"])
def test_normalize_mac_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        inventory.normalize_mac(bad)


def test_group_rejects_reversed_range(conn):
    with pytest.raises(ValidationError):
        inventory.create_group(conn, "X", [("192.0.2.20", "192.0.2.10")])


def test_group_rejects_overlap_but_allows_adjacent(conn, pc_group):
    with pytest.raises(ValidationError, match="overlaps"):
        inventory.create_group(conn, "Other", [("192.0.2.19", "192.0.2.29")])
    inventory.create_group(conn, "Other", [("192.0.2.20", "192.0.2.29")])


def test_group_name_is_unique(conn, pc_group):
    with pytest.raises(ValidationError, match="already exists"):
        inventory.create_group(conn, "PC", [("192.0.2.50", "192.0.2.59")])


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
    other = inventory.create_group(conn, "Other", [("192.0.2.20", "192.0.2.29")])
    device_id = inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.10")])
    with pytest.raises(ValidationError, match="outside the range"):
        inventory.update_device(conn, device_id, "A", other)


def test_shrinking_a_group_checks_its_devices(conn, pc_group):
    inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.18")])
    with pytest.raises(ValidationError, match="outside the new range"):
        inventory.update_group(conn, pc_group, "PC", [("192.0.2.10", "192.0.2.15")])


def test_group_with_devices_cannot_be_deleted(conn, pc_group):
    inventory.create_device(conn, "A", pc_group)
    with pytest.raises(ValidationError, match="still has"):
        inventory.delete_group(conn, pc_group)


def test_deleting_a_device_deletes_its_interfaces(conn, pc_group):
    device_id = inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", None)])
    inventory.delete_device(conn, device_id)
    assert conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0] == 0


def test_next_free_ip_skips_used_addresses(conn, pc_group):
    inventory.create_device(conn, "A", pc_group, [("aa:bb:cc:00:11:22", "192.0.2.10")])
    inventory.create_device(conn, "B", pc_group, [("aa:bb:cc:00:11:23", "192.0.2.12")])
    assert inventory.next_free_ip(conn, pc_group) == "192.0.2.11"


def test_next_free_ip_is_none_when_the_group_is_full(conn):
    group = inventory.create_group(conn, "Tiny", [("192.0.2.50", "192.0.2.50")])
    inventory.create_device(conn, "A", group, [("aa:bb:cc:00:11:22", "192.0.2.50")])
    assert inventory.next_free_ip(conn, group) is None


def test_list_types_returns_the_distinct_types_in_use(conn, pc_group):
    inventory.create_device(conn, "A", pc_group, type="laptop")
    inventory.create_device(conn, "B", pc_group, type="Desktop")
    inventory.create_device(conn, "C", pc_group, type="laptop")
    inventory.create_device(conn, "D", pc_group)
    assert inventory.list_types(conn) == ["Desktop", "laptop"]


def test_group_with_several_ranges_holds_a_device_in_each(conn):
    infra = inventory.create_group(
        conn, "Infrastructure", [("192.0.2.1", "192.0.2.9"), ("192.0.2.254", "192.0.2.254")]
    )
    inventory.create_device(
        conn,
        "Box",
        infra,
        [("aa:bb:cc:00:00:fe", "192.0.2.254"), ("aa:bb:cc:00:00:01", "192.0.2.1")],
    )
    group = inventory.get_group(conn, infra)
    assert group.contains("192.0.2.254") and group.contains("192.0.2.5")
    assert not group.contains("192.0.2.100")


def test_ip_between_two_ranges_of_a_group_is_refused(conn):
    infra = inventory.create_group(
        conn, "Infrastructure", [("192.0.2.1", "192.0.2.9"), ("192.0.2.254", "192.0.2.254")]
    )
    with pytest.raises(ValidationError, match="outside the range"):
        inventory.create_device(conn, "X", infra, [("aa:bb:cc:00:00:01", "192.0.2.100")])


def test_ranges_of_one_group_cannot_overlap_each_other(conn):
    with pytest.raises(ValidationError, match="overlap"):
        inventory.create_group(conn, "G", [("192.0.2.1", "192.0.2.9"), ("192.0.2.5", "192.0.2.20")])


def test_a_range_of_a_group_cannot_overlap_another_group(conn, pc_group):
    with pytest.raises(ValidationError, match="overlaps the group"):
        inventory.create_group(
            conn, "G", [("192.0.2.200", "192.0.2.210"), ("192.0.2.15", "192.0.2.16")]
        )
    assert [g.name for g in inventory.list_groups(conn)] == ["PC"]


def test_a_group_needs_at_least_one_range(conn):
    with pytest.raises(ValidationError, match="at least one"):
        inventory.create_group(conn, "G", [])


def test_removing_a_range_that_holds_a_device_is_refused(conn):
    infra = inventory.create_group(
        conn, "Infrastructure", [("192.0.2.1", "192.0.2.9"), ("192.0.2.254", "192.0.2.254")]
    )
    inventory.create_device(conn, "Box", infra, [("aa:bb:cc:00:00:fe", "192.0.2.254")])
    with pytest.raises(ValidationError, match="outside the new ranges"):
        inventory.update_group(conn, infra, "Infrastructure", [("192.0.2.1", "192.0.2.9")])


def test_next_free_ip_continues_in_the_next_range(conn):
    group = inventory.create_group(
        conn, "G", [("192.0.2.1", "192.0.2.1"), ("192.0.2.50", "192.0.2.51")]
    )
    inventory.create_device(conn, "A", group, [("aa:bb:cc:00:00:01", "192.0.2.1")])
    assert inventory.next_free_ip(conn, group) == "192.0.2.50"
