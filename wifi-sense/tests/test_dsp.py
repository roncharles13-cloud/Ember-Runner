"""Smoke tests for the DSP engine. Run: python -m pytest wifi-sense/tests"""

import math

from wifi_sense.dsp import SenseEngine


def _feed(engine, values, fs=20.0):
    t = 0.0
    dt = 1.0 / fs
    res = None
    for v in values:
        res = engine.add(v, t)
        t += dt
    return res


def test_quiet_room_no_motion():
    eng = SenseEngine()
    res = _feed(eng, [-55.0 + 0.01 * (i % 2) for i in range(400)])
    assert res.motion < 0.3
    assert res.presence is False


def test_motion_detected_on_large_fluctuation():
    eng = SenseEngine()
    # warm up quiet, then inject big swings
    _feed(eng, [-55.0] * 200)
    res = _feed(eng, [-55.0 + (8.0 if i % 2 else -8.0) for i in range(80)])
    assert res.motion > 0.5
    assert res.presence is True


def test_breathing_peak_recovered():
    fs = 20.0
    bpm = 15.0
    hz = bpm / 60.0
    eng = SenseEngine()
    vals = [-55.0 + 1.5 * math.sin(2 * math.pi * hz * (i / fs)) for i in range(600)]
    res = _feed(eng, vals, fs=fs)
    assert res.breathing_bpm is not None
    assert abs(res.breathing_bpm - bpm) < 3.0


def test_fs_estimate():
    eng = SenseEngine()
    res = _feed(eng, [-55.0] * 100, fs=20.0)
    assert 18.0 < res.fs < 22.0
