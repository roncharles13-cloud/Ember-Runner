"""Signal sources for the WiFi sensing pipeline.

Every source emits the same 1-D (timestamp, value) perturbation stream, so the
DSP, spectrogram, phase-portrait, server, and dashboard are identical regardless
of which sensor produced it. Only the value's meaning changes:

    rssi / ble  -> received signal strength (dBm)
    sonar       -> acoustic Doppler sideband imbalance (signed, ~0 at rest)
    lidar       -> measured range (metres)

Each real sensor has a `-sim` twin that needs no hardware.
"""

from .base import Sample, Source, paced
from .ble import BLESource, SyntheticBLESource
from .lidar import LidarSource, SyntheticLidarSource
from .replay import ReplaySource
from .rssi import RSSISource
from .sonar import SonarSource, SyntheticSonarSource
from .synthetic import SyntheticSource

KINDS = ["rssi", "synthetic", "replay",
         "sonar", "sonar-sim", "ble", "ble-sim", "lidar", "lidar-sim"]


def make_source(kind: str, **kw):
    """Factory used by the CLI."""
    hz = kw.get("hz", 20.0)
    seed = kw.get("seed")
    if kind == "rssi":
        return RSSISource(hz=hz)
    if kind == "synthetic":
        return SyntheticSource(hz=hz, breath_bpm=kw.get("breath_bpm", 15.0), seed=seed)
    if kind == "replay":
        return ReplaySource(path=kw["path"], hz=hz, loop=kw.get("loop", False))
    if kind == "sonar":
        return SonarSource(hz=hz)
    if kind == "sonar-sim":
        return SyntheticSonarSource(hz=hz, seed=seed)
    if kind == "ble":
        return BLESource(hz=kw.get("hz", 15.0), address=kw.get("address"))
    if kind == "ble-sim":
        return SyntheticBLESource(hz=kw.get("hz", 15.0), seed=seed)
    if kind == "lidar":
        return LidarSource(hz=hz, port=kw.get("port", 9099))
    if kind == "lidar-sim":
        return SyntheticLidarSource(hz=hz, seed=seed)
    raise ValueError(f"unknown source kind: {kind!r}")


__all__ = ["Sample", "Source", "paced", "make_source", "KINDS",
           "RSSISource", "SyntheticSource", "ReplaySource",
           "SonarSource", "SyntheticSonarSource",
           "BLESource", "SyntheticBLESource",
           "LidarSource", "SyntheticLidarSource"]
