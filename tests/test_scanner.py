from network_inventory import db, scanner

SAMPLE = (
    "192.0.2.11\taa:bb:cc:00:00:01\t(Unknown)\n"
    "192.0.2.42\tAA:BB:CC:00:00:02\tExample Vendor Inc.\n"
    "192.0.2.42\taa:bb:cc:00:00:02\tExample Vendor Inc. (DUP: 2)\n"
    "192.0.2.60\t3a:97:50:00:00:03\t(Unknown: locally administered)\n"
    "\n"
    "Interface: eth0, type: EN10MB\n"
    "18 packets received by filter\n"
)


def test_parse_keeps_valid_lines_only_and_dedupes():
    found = scanner.parse_arp_scan(SAMPLE)
    assert [o.mac for o in found] == [
        "aa:bb:cc:00:00:01",
        "aa:bb:cc:00:00:02",
        "3a:97:50:00:00:03",
    ]
    assert found[1].vendor == "Example Vendor Inc."
    assert found[2].vendor == "(Unknown: locally administered)"


def test_store_updates_last_seen_and_keeps_first_seen():
    conn = db.connect(":memory:")
    scanner.store_observations(conn, scanner.parse_arp_scan(SAMPLE), "2026-01-01T10:00:00Z")
    changed = scanner.parse_arp_scan("192.0.2.99\taa:bb:cc:00:00:01\t(Unknown)\n")
    scanner.store_observations(conn, changed, "2026-01-02T10:00:00Z")
    row = conn.execute("SELECT * FROM observations WHERE mac = 'aa:bb:cc:00:00:01'").fetchone()
    assert (row["ip"], row["first_seen"], row["last_seen"]) == (
        "192.0.2.99",
        "2026-01-01T10:00:00Z",
        "2026-01-02T10:00:00Z",
    )


def test_latest_scan_only_returns_the_newest_scan():
    conn = db.connect(":memory:")
    scanner.store_observations(conn, scanner.parse_arp_scan(SAMPLE), "2026-01-01T10:00:00Z")
    scanner.store_observations(
        conn, scanner.parse_arp_scan("192.0.2.11\taa:bb:cc:00:00:01\tx\n"), "2026-01-02T10:00:00Z"
    )
    assert [o.mac for o in scanner.latest_scan(conn)] == ["aa:bb:cc:00:00:01"]


HEADER = "Interface: eth0, type: EN10MB, MAC: 50:eb:f6:00:00:99, IPv4: 192.0.2.5\n"


def test_the_scanning_machine_is_read_from_the_header():
    found = scanner.parse_arp_scan(HEADER + SAMPLE)
    assert found[0] == scanner.Observation("50:eb:f6:00:00:99", "192.0.2.5", scanner.SELF_VENDOR)
    assert len(found) == 4


def test_a_header_with_a_bad_address_is_ignored():
    bad = "Interface: eth0, type: EN10MB, MAC: nonsense, IPv4: 192.0.2.5\n"
    assert len(scanner.parse_arp_scan(bad + SAMPLE)) == 3


def test_no_header_means_no_local_machine():
    assert all(o.vendor != scanner.SELF_VENDOR for o in scanner.parse_arp_scan(SAMPLE))
