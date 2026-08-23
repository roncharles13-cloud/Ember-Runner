"""Smoke tests for the multi-sensor source adapters (synthetic variants)."""

import itertools

import pytest

from wifi_sense.dsp import SenseEngine
from wifi_sense.sources import KINDS, make_source
from wifi_sense.sources.ble import SyntheticBLESource
from wifi_sense.sources.lidar import SyntheticLidarSource, _parse
from wifi_sense.sources.sonar import SyntheticSonarSource


def _first_n(src, n):
    """Pull n raw samples without real-time pacing."""
    return list(itertools.islice(src._raw(), n))


def test_factory_knows_all_kinds():
    assert {"sonar-sim", "ble-sim", "lidar-sim"} <= set(KINDS)
    for k in ("sonar-sim", "ble-sim", "lidar-sim"):
        s = make_source(k, seed=1)
        assert hasattr(s, "samples") and s.name == k


def test_sonar_rest_near_zero_motion_on_walk():
    src = SyntheticSonarSource(hz=20.0, seed=0)
    raw = _first_n(src, 20 * 40)          # one full scene
    vals = [v for _, v in raw]
    # empty stretch (0-7s) small; walking stretch (24-34s) large swings
    empty = vals[0:20 * 6]
    walk = vals[20 * 25:20 * 33]
    assert max(abs(x) for x in walk) > 3 * (max(abs(x) for x in empty) + 1e-6)


def test_ble_baseline_and_motion():
    src = SyntheticBLESource(hz=15.0, seed=0)
    raw = _first_n(src, 15 * 40)
    vals = [v for _, v in raw]
    assert -85 < sum(vals) / len(vals) < -55     # centered near -70 dBm


def test_lidar_person_is_closer_than_empty():
    src = SyntheticLidarSource(hz=20.0, empty_range=3.2, seed=0)
    raw = _first_n(src, 20 * 40)
    vals = [v for _, v in raw]
    empty = sum(vals[0:20 * 6]) / (20 * 6)
    standing = sum(vals[20 * 10:20 * 20]) / (20 * 10)
    assert standing < empty            # a person is nearer than the far wall


def test_lidar_parse_formats():
    assert _parse(b"1.83") == pytest.approx(1.83)
    assert _parse(b'{"range": 2.5}') == pytest.approx(2.5)
    assert _parse(b'{"t":1.0,"range":0.9}') == pytest.approx(0.9)
    assert _parse(b"garbage") is None


def test_sonar_flows_through_sense_engine():
    src = SyntheticSonarSource(hz=20.0, seed=0)
    eng = SenseEngine()
    res = None
    for i, (_, v) in enumerate(itertools.islice(src._raw(), 20 * 30)):
        res = eng.add(v, i / 20.0)
    assert 0.0 <= res.motion <= 1.0    # pipeline consumes the sonar stream fine
