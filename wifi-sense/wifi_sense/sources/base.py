"""Source interface.

A source yields (timestamp, rssi_dBm) samples. Swap the source and the rest of
the pipeline (dsp + server + dashboard) is untouched — this is where a real CSI
adapter (ESP32 serial, Nexmon UDP, PicoScenes) would plug in later, emitting a
richer per-subcarrier payload instead of a single RSSI scalar.
"""

from __future__ import annotations

import time
from typing import Iterator, Protocol, Tuple

Sample = Tuple[float, float]  # (unix_time, rssi_dBm)


class Source(Protocol):
    name: str

    def samples(self) -> Iterator[Sample]:
        """Yield (timestamp, rssi) forever (or until exhausted)."""
        ...


def paced(iterator: Iterator[Sample], hz: float) -> Iterator[Sample]:
    """Re-time an iterator so it yields at approximately `hz` samples/sec.

    Used by synthetic/replay sources whose data isn't inherently real-time.
    """
    period = 1.0 / hz
    next_t = time.time()
    for _, rssi in iterator:
        now = time.time()
        sleep = next_t - now
        if sleep > 0:
            time.sleep(sleep)
        next_t += period
        yield time.time(), rssi
