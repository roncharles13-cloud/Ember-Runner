"""Synthetic RSSI source.

Generates a believable RSSI stream so you can see the whole pipeline
(motion -> presence -> breathing) working on any PC with no WiFi hardware
access at all. It models:

  * a stable baseline (router link) with mild noise  -> "empty room"
  * a slow sinusoid in the breathing band            -> "still person breathing"
  * occasional bursts of large fluctuation           -> "person moving"

Use it to sanity-check the dashboard and DSP, then switch --source rssi for the
real thing.
"""

from __future__ import annotations

import math
import random
from typing import Iterator

from .base import Sample, paced


class SyntheticSource:
    name = "synthetic"

    def __init__(self, hz: float = 20.0, baseline: float = -55.0,
                 breath_bpm: float = 15.0, seed: int | None = None):
        self.hz = hz
        self.baseline = baseline
        self.breath_hz = breath_bpm / 60.0
        self.rng = random.Random(seed)

    def _raw(self) -> Iterator[Sample]:
        t = 0.0
        dt = 1.0 / self.hz
        # Scripted scene: quiet -> breathing -> motion -> quiet, looping.
        while True:
            phase = (t % 40.0)
            noise = self.rng.gauss(0, 0.4)
            val = self.baseline + noise
            if 8.0 <= phase < 22.0:
                # still person breathing near the link
                val += 1.6 * math.sin(2 * math.pi * self.breath_hz * t)
            elif 24.0 <= phase < 34.0:
                # someone moving through the link
                val += self.rng.gauss(0, 4.0) + 3.0 * math.sin(2 * math.pi * 0.8 * t)
            yield 0.0, val
            t += dt

    def samples(self) -> Iterator[Sample]:
        return paced(self._raw(), self.hz)
