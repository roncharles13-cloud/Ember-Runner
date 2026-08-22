"""Signal processing for single-stream WiFi RSSI sensing.

Everything here operates on a rolling window of RSSI samples (dBm) that arrive
at a roughly fixed rate. From that one scalar-per-sample stream we can honestly
extract:

  * motion     - short-term variance/energy of the detrended signal
  * presence    - a debounced threshold on the motion energy
  * breathing   - dominant frequency in the 0.1-0.6 Hz band (only reliable when
                  the subject is close to the link and otherwise still)

We deliberately avoid scipy so the package installs with just numpy. The
band-power/rate estimate uses a windowed FFT, and detrending uses a simple
moving-average high-pass, both of which are plenty for RSSI-rate data.
"""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field

import numpy as np

# Breathing band in Hz. Normal adult resting respiration is ~0.2-0.33 Hz
# (12-20 breaths/min); we widen it a little on both ends.
BREATH_LO_HZ = 0.10
BREATH_HI_HZ = 0.60


@dataclass
class SenseResult:
    t: float
    rssi: float                 # latest raw sample (dBm)
    motion: float               # 0..1 normalized motion energy
    presence: bool              # debounced presence flag
    breathing_bpm: float | None # breaths per minute, or None if not confident
    breathing_conf: float       # 0..1 confidence in the breathing estimate
    fs: float                   # estimated sample rate (Hz)


@dataclass
class SenseEngine:
    """Stateful estimator fed one RSSI sample at a time."""

    window_sec: float = 30.0            # analysis window length
    motion_win_sec: float = 2.0         # short window for the motion metric
    presence_on: float = 0.12           # motion energy to declare "present"
    presence_off: float = 0.06          # hysteresis: fall below this to clear
    presence_hold_sec: float = 3.0      # keep presence up this long after motion
    _samples: collections.deque = field(default_factory=collections.deque)
    _times: collections.deque = field(default_factory=collections.deque)
    _present: bool = False
    _last_motion_t: float = 0.0
    _motion_ref: float = 1.0            # adaptive normalizer for motion energy

    def add(self, rssi: float, t: float | None = None) -> SenseResult:
        now = time.time() if t is None else t
        self._samples.append(float(rssi))
        self._times.append(now)
        self._trim(now)

        fs = self._estimate_fs()
        motion = self._motion(fs)
        presence = self._presence(motion, now)
        bpm, conf = self._breathing(fs)

        return SenseResult(
            t=now,
            rssi=float(rssi),
            motion=motion,
            presence=presence,
            breathing_bpm=bpm,
            breathing_conf=conf,
            fs=fs,
        )

    # -- internals -------------------------------------------------------

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
            self._samples.popleft()

    def _estimate_fs(self) -> float:
        if len(self._times) < 4:
            return 0.0
        span = self._times[-1] - self._times[0]
        if span <= 0:
            return 0.0
        return (len(self._times) - 1) / span

    def _detrended(self) -> np.ndarray:
        x = np.asarray(self._samples, dtype=float)
        if x.size < 3:
            return x - x.mean() if x.size else x
        # Moving-average high-pass: subtract a slow baseline so DC/router-power
        # drift doesn't swamp the small body-motion fluctuations.
        k = max(3, int(x.size * 0.15) | 1)  # odd kernel ~15% of window
        pad = k // 2
        padded = np.pad(x, pad, mode="edge")
        kernel = np.ones(k) / k
        baseline = np.convolve(padded, kernel, mode="valid")
        return x - baseline

    def _motion(self, fs: float) -> float:
        n = len(self._samples)
        if n < 4 or fs <= 0:
            return 0.0
        d = self._detrended()
        m = max(3, int(self.motion_win_sec * fs))
        recent = d[-m:] if d.size >= m else d
        energy = float(np.sqrt(np.mean(recent ** 2)))  # RMS of fluctuations
        # Adaptive normalization: track a slow floor so different rooms/cards
        # self-calibrate. Motion is energy relative to that quiet floor.
        self._motion_ref = 0.995 * self._motion_ref + 0.005 * max(energy, 1e-3)
        norm = energy / max(self._motion_ref * 3.0, 0.5)
        return float(np.clip(norm, 0.0, 1.0))

    def _presence(self, motion: float, now: float) -> bool:
        if motion >= self.presence_on:
            self._present = True
            self._last_motion_t = now
        elif motion < self.presence_off:
            if now - self._last_motion_t > self.presence_hold_sec:
                self._present = False
        return self._present

    def _breathing(self, fs: float) -> tuple[float | None, float]:
        n = len(self._samples)
        # Need enough of the window and a sane rate to resolve ~0.1-0.6 Hz.
        if fs < 1.5 or n < int(fs * 12):
            return None, 0.0
        d = self._detrended()
        d = d - d.mean()
        win = np.hanning(d.size)
        spec = np.abs(np.fft.rfft(d * win)) ** 2
        freqs = np.fft.rfftfreq(d.size, d=1.0 / fs)

        band = (freqs >= BREATH_LO_HZ) & (freqs <= BREATH_HI_HZ)
        if not np.any(band):
            return None, 0.0
        band_spec = spec[band]
        band_freqs = freqs[band]
        peak_i = int(np.argmax(band_spec))
        peak_f = float(band_freqs[peak_i])
        peak_p = float(band_spec[peak_i])

        # Confidence: how much the peak stands out from the rest of the band.
        others = np.delete(band_spec, peak_i)
        med = float(np.median(others)) if others.size else 0.0
        prominence = peak_p / (med + 1e-9)
        conf = float(np.clip((prominence - 3.0) / 12.0, 0.0, 1.0))

        if conf <= 0.0:
            return None, 0.0
        return peak_f * 60.0, conf
