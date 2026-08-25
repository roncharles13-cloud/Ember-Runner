"""Smoke tests for the RF device radar (synthetic scanner)."""

import itertools

from wifi_sense.radar import SyntheticRadarScanner, make_scanner, short_id


def test_short_id_is_stable_and_short():
    a = short_id("AA:BB:CC:DD:EE:FF")
    assert a == short_id("AA:BB:CC:DD:EE:FF")
    assert len(a) == 6
    assert a != short_id("11:22:33:44:55:66")


def test_factory():
    s = make_scanner("radar-sim", seed=1)
    assert s.name == "radar-sim"


def test_snapshot_shape_and_fields():
    s = SyntheticRadarScanner(hz=1000.0, seed=2)   # fast tick for testing
    snap = next(iter(s.snapshots()))
    for d in snap:
        assert set(d) >= {"id", "rssi", "kind", "name", "age", "held"}
        assert d["kind"] in ("apple", "ble")
        assert -100 <= d["rssi"] <= -30


def test_sees_some_devices_over_time():
    s = SyntheticRadarScanner(hz=1000.0, seed=3)
    seen = set()
    for snap in itertools.islice(s.snapshots(), 40):
        for d in snap:
            seen.add(d["id"])
    assert len(seen) >= 1      # at least one device advertised across the window
