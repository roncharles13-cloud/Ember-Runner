"""LiDAR / depth source — motion from changes in measured distance.

Laptops have no LiDAR; Pro iPhones/iPads do (the ARKit depth sensor). So the
real path here is an *ingest*: a companion app or Shortcut on the device streams
depth readings to this machine over UDP, and we turn them into the shared
perturbation value. The natural value is the mean (or nearest) range in a region
of interest — when a body enters or moves, that distance changes, and its
fluctuation is motion. Because LiDAR gives true depth, this is the one on-device
sensor here that also carries coarse *shape/position*, not just "something moved".

Wire format (one reading per UDP datagram), any of:
    12.34                       # a bare number = metres
    {"range": 1.83}             # JSON with a 'range' key (metres)
    {"t": 1712.5, "range": 1.83}

Send from an iPhone with a tiny ARKit app or a Shortcut that POSTs the scene's
average depth. No hardware here → use `--source lidar-sim`.
"""

from __future__ import annotations

import json
import math
import random
import socket
import time
from typing import Iterator

from .base import Sample, paced


def _parse(datagram: bytes):
    text = datagram.decode("utf-8", "ignore").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "range" in obj:
            return float(obj["range"])
    except (ValueError, TypeError):
        pass
    return None


class LidarSource:
    """Ingest a depth/range stream over UDP (metres)."""

    name = "lidar"

    def __init__(self, hz: float = 20.0, host: str = "0.0.0.0", port: int = 9099):
        self.hz = hz
        self.host = host
        self.port = port
        self.backend = f"udp {host}:{port}"

    def samples(self) -> Iterator[Sample]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.host, self.port))
        sock.settimeout(2.0)
        last = None
        while True:
            try:
                data, _ = sock.recvfrom(1024)
            except socket.timeout:
                if last is not None:
                    yield time.time(), last     # hold last reading if stream pauses
                continue
            v = _parse(data)
            if v is None:
                continue
            last = v
            yield time.time(), v


class SyntheticLidarSource:
    """No-hardware depth scene: empty room far, a person approaches, breathes, leaves."""

    name = "lidar-sim"

    def __init__(self, hz: float = 20.0, empty_range: float = 3.2,
                 breath_bpm: float = 15.0, seed=None):
        self.hz = hz
        self.empty = empty_range              # metres to the far wall
        self.breath_hz = breath_bpm / 60.0
        self.rng = random.Random(seed)
        self.backend = "simulated depth"

    def _raw(self) -> Iterator[Sample]:
        t, dt = 0.0, 1.0 / self.hz
        while True:
            phase = t % 40.0
            rng = self.empty + self.rng.gauss(0, 0.01)       # quiet: far wall, low noise
            if 8.0 <= phase < 22.0:                          # person standing still, breathing
                rng = 1.4 + 0.02 * math.sin(2 * math.pi * self.breath_hz * t)
            elif 24.0 <= phase < 34.0:                       # walking across: range swings
                rng = 1.8 + 0.9 * math.sin(2 * math.pi * 0.4 * t) + self.rng.gauss(0, 0.05)
            yield 0.0, rng
            t += dt

    def samples(self) -> Iterator[Sample]:
        return paced(self._raw(), self.hz)
