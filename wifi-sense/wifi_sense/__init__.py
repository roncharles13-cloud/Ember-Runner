"""wifi_sense - laptop-only WiFi sensing toolkit (RSSI tier).

Presence + motion (reliable), breathing rate (marginal) from your laptop's own
WiFi card, with a live browser dashboard. Designed so a real CSI source can be
dropped in later without touching the DSP, server, or dashboard.
"""

__version__ = "0.1.0"

from .dsp import SenseEngine, SenseResult

__all__ = ["SenseEngine", "SenseResult", "__version__"]
