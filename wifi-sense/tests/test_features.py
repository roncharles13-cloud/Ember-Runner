"""Smoke tests for the latent-axis FeatureEngine."""

import math

from wifi_sense.features import BANDS, FMAX_HZ, NBINS, FeatureEngine


def _feed(eng, values, fs=20.0):
    t, dt, frame = 0.0, 1.0 / fs, None
    for v in values:
        frame = eng.add(v, t)
        t += dt
    return frame


def test_spectrogram_shape_and_range():
    eng = FeatureEngine()
    f = _feed(eng, [-55.0 + 0.3 * math.sin(i) for i in range(300)])
    assert len(f.spec) == NBINS
    assert all(0.0 <= v <= 1.0 for v in f.spec)
    assert f.fmax == FMAX_HZ


def test_breathing_lands_in_breathing_band():
    fs = 20.0
    hz = 0.25  # 15 bpm
    eng = FeatureEngine()
    vals = [-55.0 + 1.5 * math.sin(2 * math.pi * hz * (i / fs)) for i in range(400)]
    f = _feed(eng, vals, fs=fs)
    # breathing band should dominate limb/fast for a pure slow sinusoid
    assert f.bands["breathing"] > f.bands["limb"]
    assert f.bands["breathing"] > f.bands["fast"]
    assert set(f.bands) == set(BANDS)


def test_fast_motion_lifts_higher_bands():
    fs = 20.0
    eng = FeatureEngine()
    # broadband-ish fast fluctuation
    import random
    rng = random.Random(0)
    vals = [-55.0 + rng.gauss(0, 3) + 2 * math.sin(2 * math.pi * 2.2 * i / fs)
            for i in range(400)]
    f = _feed(eng, vals, fs=fs)
    assert f.bands["fast"] > 0.05


def test_embedding_present_and_pair():
    eng = FeatureEngine()
    f = _feed(eng, [-55.0 + math.sin(i * 0.3) for i in range(200)])
    assert f.embed is not None and len(f.embed) == 2
    assert f.tau >= 1


def test_empty_room_embedding_collapses():
    eng = FeatureEngine()
    f = _feed(eng, [-55.0] * 200)          # dead flat
    assert f.embed == [0.0, 0.0]
