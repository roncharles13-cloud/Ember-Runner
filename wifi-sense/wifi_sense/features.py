"""Latent-axis feature extraction — manufacturing new dimensions from 1D RSSI.

The capture card gives us one scalar per sample. This module recovers extra
"axes" of information from that single stream using only math (no new hardware):

  * SPECTROGRAM (time x frequency) — a short-time Fourier transform. Different
    motions live in different frequency bands, so a scalar becomes a 2D image of
    "what kind of movement, when". Breathing sits low (~0.2 Hz); limb motion and
    walking spread higher and broadband.

  * DELAY EMBEDDING (Takens' theorem) — plot the signal against time-delayed
    copies of itself, s(t) vs s(t-tau). A 1D time series unfolds into a
    higher-dimensional "phase portrait" whose *shape* encodes the system's
    state: still breathing traces a clean loop (a limit cycle); walking smears
    into a cloud; an empty room collapses to a dot. This is the highest
    information-per-flop trick available on a single sensor.

  * BAND ENERGIES — breathing / limb / fast bands as three live scalars, a
    compact readout of the spectrogram.

Depends only on numpy. Runs alongside dsp.SenseEngine; neither needs the other.
"""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field

import numpy as np

# Display range: human motion at RSSI sample rates lives below a few Hz.
FMAX_HZ = 3.0
NBINS = 56          # spectrogram frequency bins across 0..FMAX_HZ

# Band edges (Hz) for the three energy readouts.
BANDS = {
    "breathing": (0.10, 0.60),
    "limb":      (0.60, 1.80),
    "fast":      (1.80, 3.00),
}


def detrend(x: np.ndarray) -> np.ndarray:
    """Moving-average high-pass: strip slow router-power drift, keep motion."""
    if x.size < 3:
        return x - x.mean() if x.size else x
    k = max(3, int(x.size * 0.15) | 1)
    pad = k // 2
    padded = np.pad(x, pad, mode="edge")
    baseline = np.convolve(padded, np.ones(k) / k, mode="valid")
    return x - baseline


@dataclass
class FeatureFrame:
    spec: list          # NBINS floats in 0..1 (newest spectrogram column)
    bands: dict         # {breathing, limb, fast} each 0..1
    embed: list | None  # [x, y] newest delay-embedded point (normalized), or None
    tau: int            # embedding delay in samples
    fmax: float
    nbins: int


@dataclass
class FeatureEngine:
    win_sec: float = 12.0        # STFT window (sets breathing freq resolution)
    embed_tau_sec: float = 0.9   # delay ~ quarter of a breathing cycle
    _s: collections.deque = field(default_factory=collections.deque)
    _t: collections.deque = field(default_factory=collections.deque)
    _ref: float = 1e-6           # adaptive brightness reference for the spectrogram

    def add(self, rssi: float, t: float | None = None) -> FeatureFrame:
        now = time.time() if t is None else t
        self._s.append(float(rssi))
        self._t.append(now)
        cutoff = now - self.win_sec
        while self._t and self._t[0] < cutoff:
            self._t.popleft()
            self._s.popleft()

        fs = self._fs()
        spec = self._spectrogram_column(fs)
        bands = self._bands(fs)
        embed, tau = self._embedding(fs)
        return FeatureFrame(spec=spec, bands=bands, embed=embed, tau=tau,
                            fmax=FMAX_HZ, nbins=NBINS)

    # -- internals -------------------------------------------------------

    def _fs(self) -> float:
        if len(self._t) < 4:
            return 0.0
        span = self._t[-1] - self._t[0]
        return (len(self._t) - 1) / span if span > 0 else 0.0

    def _power(self, fs: float):
        n = len(self._s)
        if fs <= 0 or n < 16:
            return None, None
        x = detrend(np.asarray(self._s, dtype=float))
        x = x - x.mean()
        win = np.hanning(x.size)
        spec = np.abs(np.fft.rfft(x * win)) ** 2
        freqs = np.fft.rfftfreq(x.size, d=1.0 / fs)
        return freqs, spec

    def _spectrogram_column(self, fs: float) -> list:
        freqs, spec = self._power(fs)
        if freqs is None:
            return [0.0] * NBINS
        targets = np.linspace(0.0, FMAX_HZ, NBINS)
        col = np.interp(targets, freqs, spec, left=0.0, right=0.0)
        val = np.log1p(col)                      # perceptual compression
        self._ref = max(self._ref * 0.995, float(val.max()), 1e-6)
        out = np.clip(val / (self._ref + 1e-9), 0.0, 1.0)
        return [round(float(v), 3) for v in out]

    def _bands(self, fs: float) -> dict:
        freqs, spec = self._power(fs)
        if freqs is None:
            return {k: 0.0 for k in BANDS}
        total = float(spec.sum()) + 1e-9
        out = {}
        for name, (lo, hi) in BANDS.items():
            m = (freqs >= lo) & (freqs < hi)
            out[name] = round(float(spec[m].sum()) / total, 3)
        return out

    def _embedding(self, fs: float):
        n = len(self._s)
        if fs <= 0:
            return None, 0
        tau = max(1, int(self.embed_tau_sec * fs))
        if n < tau + 2:
            return None, tau
        x = detrend(np.asarray(self._s, dtype=float))
        sd = float(x.std())
        if sd < 1e-6:
            return [0.0, 0.0], tau           # empty room: collapses to origin
        x = x / sd
        return [round(float(x[-1]), 3), round(float(x[-1 - tau]), 3)], tau
