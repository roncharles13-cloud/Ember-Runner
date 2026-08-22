"""Live RSSI capture from the laptop's own WiFi card.

No special chipset, no monitor mode, no sudo (on Linux) required — we just poll
the OS for the current link's signal strength as fast as the platform allows and
turn that scalar stream into motion/presence/breathing downstream.

Backends, auto-selected by platform:

  Linux   : /proc/net/wireless  (fast, no privileges). Falls back to `iw`.
  macOS   : `wdutil info` (modern) or the legacy `airport -I`.
  Windows : `netsh wlan show interfaces` (Signal % -> approx dBm).

Reality check: these OS interfaces refresh RSSI slowly (often 1-10 Hz, sometimes
capped) and quantize it. That's why this tier does motion/presence reliably but
breathing only marginally. A real CSI source removes this ceiling — see
sources/base.py for where it plugs in.
"""

from __future__ import annotations

import platform
import re
import subprocess
import time
from typing import Callable, Iterator, Optional

from .base import Sample


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout + out.stderr
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


# -- Linux -----------------------------------------------------------------

def _linux_proc_reader() -> Optional[Callable[[], Optional[float]]]:
    path = "/proc/net/wireless"
    try:
        with open(path):
            pass
    except OSError:
        return None

    def read() -> Optional[float]:
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError:
            return None
        # Skip two header lines; each iface line: "wlan0: 0000 70. -40. ..."
        for line in lines[2:]:
            parts = line.split()
            if len(parts) >= 4:
                level = parts[3].rstrip(".")
                try:
                    return float(level)  # already dBm
                except ValueError:
                    continue
        return None

    # Only use it if it actually returns a value right now.
    return read if read() is not None else None


def _linux_iw_reader() -> Optional[Callable[[], Optional[float]]]:
    iface = _linux_default_iface()
    if not iface:
        return None
    sig_re = re.compile(r"signal:\s*(-?\d+)\s*dBm")

    def read() -> Optional[float]:
        text = _run(["iw", "dev", iface, "link"])
        m = sig_re.search(text)
        return float(m.group(1)) if m else None

    return read if read() is not None else None


def _linux_default_iface() -> Optional[str]:
    text = _run(["iw", "dev"])
    m = re.search(r"Interface\s+(\S+)", text)
    if m:
        return m.group(1)
    # Fallback: first wireless iface in /proc/net/wireless
    try:
        with open("/proc/net/wireless") as f:
            for line in f.readlines()[2:]:
                name = line.split(":")[0].strip()
                if name:
                    return name
    except OSError:
        pass
    return None


# -- macOS -----------------------------------------------------------------

def _macos_reader() -> Optional[Callable[[], Optional[float]]]:
    airport = ("/System/Library/PrivateFrameworks/Apple80211.framework/"
               "Versions/Current/Resources/airport")
    rssi_re = re.compile(r"agrCtlRSSI:\s*(-?\d+)")
    wdutil_re = re.compile(r"RSSI\s*:\s*(-?\d+)")

    def read() -> Optional[float]:
        text = _run([airport, "-I"])
        m = rssi_re.search(text)
        if m:
            return float(m.group(1))
        # Newer macOS deprecates airport; wdutil needs sudo but try anyway.
        text = _run(["wdutil", "info"])
        m = wdutil_re.search(text)
        return float(m.group(1)) if m else None

    return read if read() is not None else None


# -- Windows ---------------------------------------------------------------

def _windows_reader() -> Optional[Callable[[], Optional[float]]]:
    sig_re = re.compile(r"Signal\s*:\s*(\d+)%")

    def read() -> Optional[float]:
        text = _run(["netsh", "wlan", "show", "interfaces"])
        m = sig_re.search(text)
        if not m:
            return None
        pct = float(m.group(1))
        # netsh reports link quality %; map to approx dBm (common heuristic:
        # 0% -> -100 dBm, 100% -> -50 dBm).
        return pct / 2.0 - 100.0

    return read if read() is not None else None


def _select_reader() -> tuple[str, Callable[[], Optional[float]]]:
    system = platform.system()
    candidates: list[tuple[str, Callable[[], Optional[Callable]]]] = []
    if system == "Linux":
        candidates = [("proc", _linux_proc_reader), ("iw", _linux_iw_reader)]
    elif system == "Darwin":
        candidates = [("airport/wdutil", _macos_reader)]
    elif system == "Windows":
        candidates = [("netsh", _windows_reader)]

    for label, factory in candidates:
        reader = factory()
        if reader is not None:
            return label, reader

    raise RuntimeError(
        f"No working RSSI backend on {system}. "
        "Are you connected to WiFi? On Linux ensure /proc/net/wireless exists "
        "or `iw` is installed; on macOS try running with sudo for wdutil; "
        "on Windows ensure you're associated to an AP. "
        "You can always fall back to `--source synthetic`."
    )


class RSSISource:
    name = "rssi"

    def __init__(self, hz: float = 20.0):
        self.hz = hz
        self.backend, self._read = _select_reader()

    def samples(self) -> Iterator[Sample]:
        period = 1.0 / self.hz
        last: Optional[float] = None
        next_t = time.time()
        while True:
            now = time.time()
            sleep = next_t - now
            if sleep > 0:
                time.sleep(sleep)
            next_t += period
            val = self._read()
            if val is None:
                val = last if last is not None else -100.0
            last = val
            yield time.time(), val
