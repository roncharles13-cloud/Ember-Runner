"""Signal sources for the WiFi sensing pipeline."""

from .base import Sample, Source, paced
from .replay import ReplaySource
from .rssi import RSSISource
from .synthetic import SyntheticSource


def make_source(kind: str, **kwargs):
    """Factory used by the CLI. `kind` is one of: rssi, synthetic, replay."""
    if kind == "rssi":
        return RSSISource(hz=kwargs.get("hz", 20.0))
    if kind == "synthetic":
        return SyntheticSource(hz=kwargs.get("hz", 20.0),
                               breath_bpm=kwargs.get("breath_bpm", 15.0),
                               seed=kwargs.get("seed"))
    if kind == "replay":
        return ReplaySource(path=kwargs["path"], hz=kwargs.get("hz", 20.0),
                            loop=kwargs.get("loop", False))
    raise ValueError(f"unknown source kind: {kind!r}")


__all__ = ["Sample", "Source", "paced", "make_source",
           "RSSISource", "SyntheticSource", "ReplaySource"]
