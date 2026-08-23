"""Bluetooth LE RSSI source — motion from how a body perturbs a BLE link.

Same physics as the WiFi RSSI source, on a different radio: a body moving
between your machine and a BLE advertiser (a beacon, a phone, earbuds, a smart
bulb) modulates the received signal strength. BLE advertises often (~10 Hz) and
is cheap to scan, so it's a handy second radio channel.

We continuously scan BLE advertisements and track the RSSI of one device — a
target address if you give one, else the strongest steady advertiser we see. The
RSSI (dBm) is the perturbation value fed to the shared pipeline; its fluctuation
is motion, exactly like WiFi.

Real capture needs `bleak` (pip install bleak) and Bluetooth permission. If it's
missing, use `--source ble-sim` for a no-hardware demo.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Iterator, Optional

from .base import Sample, paced


class BLESource:
    """Live BLE RSSI via a background bleak scanner."""

    name = "ble"

    def __init__(self, hz: float = 15.0, address: Optional[str] = None):
        self.hz = hz
        self.address = address
        self.backend = f"target {address}" if address else "strongest advertiser"
        self._rssi: Optional[float] = None
        self._lock = threading.Lock()
        try:
            import bleak  # noqa: F401
        except Exception as e:
            raise RuntimeError(
                "BLE sensing needs the 'bleak' package.\n"
                "  pip install bleak\n"
                "Grant Bluetooth permission, or use --source ble-sim for a demo."
            ) from e

    def _run_scanner(self):
        import asyncio
        from bleak import BleakScanner

        seen: dict[str, float] = {}

        def cb(device, adv):
            rssi = adv.rssi if adv.rssi is not None else getattr(device, "rssi", None)
            if rssi is None:
                return
            if self.address:
                if device.address.lower() == self.address.lower():
                    with self._lock:
                        self._rssi = float(rssi)
            else:
                seen[device.address] = float(rssi)
                # lock onto the strongest advertiser
                best = max(seen.values())
                with self._lock:
                    self._rssi = best

        async def main():
            scanner = BleakScanner(detection_callback=cb)
            await scanner.start()
            while True:
                await asyncio.sleep(3600)

        asyncio.new_event_loop().run_until_complete(main())

    def samples(self) -> Iterator[Sample]:
        threading.Thread(target=self._run_scanner, daemon=True).start()
        period, last = 1.0 / self.hz, None
        next_t = time.time()
        while True:
            now = time.time()
            if next_t - now > 0:
                time.sleep(next_t - now)
            next_t += period
            with self._lock:
                v = self._rssi
            if v is None:
                v = last if last is not None else -90.0
            last = v
            yield time.time(), v


class SyntheticBLESource:
    """No-hardware BLE scene: noisier/coarser than WiFi, centered ~ -70 dBm."""

    name = "ble-sim"

    def __init__(self, hz: float = 15.0, baseline: float = -70.0,
                 breath_bpm: float = 15.0, seed=None):
        self.hz = hz
        self.baseline = baseline
        self.breath_hz = breath_bpm / 60.0
        self.rng = random.Random(seed)
        self.backend = "simulated advertiser"

    def _raw(self) -> Iterator[Sample]:
        t, dt = 0.0, 1.0 / self.hz
        while True:
            phase = t % 40.0
            val = self.baseline + self.rng.gauss(0, 1.0)     # BLE is noisier
            if 8.0 <= phase < 22.0:
                val += 1.2 * math.sin(2 * math.pi * self.breath_hz * t)
            elif 24.0 <= phase < 34.0:
                val += self.rng.gauss(0, 5.0)
            yield 0.0, val
            t += dt

    def samples(self) -> Iterator[Sample]:
        return paced(self._raw(), self.hz)
