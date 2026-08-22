"""Replay a recorded capture (CSV) back through the pipeline.

CSV format (header optional): each line is `timestamp,rssi` or just `rssi`.
Recordings are produced by running the CLI with --record <file>. Handy for
sharing a capture, debugging DSP offline, or building a labelled dataset.
"""

from __future__ import annotations

import csv
from typing import Iterator

from .base import Sample, paced


class ReplaySource:
    name = "replay"

    def __init__(self, path: str, hz: float = 20.0, loop: bool = False):
        self.path = path
        self.hz = hz
        self.loop = loop

    def _rows(self) -> Iterator[float]:
        while True:
            with open(self.path, newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    cell = row[-1].strip()
                    try:
                        yield float(cell)
                    except ValueError:
                        continue  # header or comment line
            if not self.loop:
                return

    def samples(self) -> Iterator[Sample]:
        return paced(((0.0, v) for v in self._rows()), self.hz)
