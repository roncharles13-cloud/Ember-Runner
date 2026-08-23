"""Acoustic sonar source — active motion sensing with the speaker + mic.

Unlike WiFi RSSI (where we only eavesdrop on someone else's signal), here we
*emit* the probe ourselves, so the SNR is far higher and the sample rate is
~48 kHz instead of ~20 Hz:

  1. The speaker plays a steady inaudible tone at f0 (~19 kHz).
  2. Anything moving in the room Doppler-shifts the echo — toward the device
     shifts it up, away shifts it down (delta_f = 2*v*f0 / c_sound).
  3. We FFT the mic signal around f0 and measure the imbalance between the upper
     and lower sidebands. That signed number is our perturbation value: ~0 at
     rest, positive/negative with the direction of motion.

That single number flows through the same SenseEngine + FeatureEngine as RSSI,
so motion / presence / spectrogram / phase-portrait all work unchanged — but the
detection is dramatically crisper because we control the transmit waveform.

Real capture needs PortAudio via `sounddevice` (pip install sounddevice). If it
is missing or there is no audio device, use `--source sonar-sim` for a synthetic
Doppler scene that runs anywhere.
"""

from __future__ import annotations

import math
import queue
import random
from typing import Iterator

from .base import Sample, paced

# Acoustic constants
CARRIER_HZ = 19000.0     # inaudible to most adults, within laptop mic/speaker range
SPEED_SOUND = 343.0      # m/s
SIDEBAND_HZ = 600.0      # +/- window around carrier we analyze


class SonarSource:
    """Live acoustic sonar via the default speaker + microphone."""

    name = "sonar"

    def __init__(self, hz: float = 20.0, samplerate: int = 48000,
                 carrier: float = CARRIER_HZ, block: int = 2048):
        self.hz = hz
        self.samplerate = samplerate
        self.carrier = carrier
        self.block = block
        self.backend = f"{int(carrier)}Hz tone"
        try:
            import numpy as np  # noqa: F401
            import sounddevice as sd  # noqa: F401
        except Exception as e:  # ImportError or PortAudio load error
            raise RuntimeError(
                "acoustic sonar needs the 'sounddevice' package and PortAudio.\n"
                "  pip install sounddevice\n"
                "Then re-run, or use --source sonar-sim for a no-hardware demo."
            ) from e

    def samples(self) -> Iterator[Sample]:
        import numpy as np
        import sounddevice as sd
        import time

        q: "queue.Queue[tuple[float, float]]" = queue.Queue(maxsize=256)
        sr = self.samplerate
        w = self.carrier
        phase = 0.0
        dphase = 2 * math.pi * w / sr
        freqs = np.fft.rfftfreq(self.block, d=1.0 / sr)
        up = (freqs > w) & (freqs <= w + SIDEBAND_HZ)
        lo = (freqs < w) & (freqs >= w - SIDEBAND_HZ)
        window = np.hanning(self.block)

        def callback(indata, outdata, frames, tinfo, status):
            nonlocal phase
            # emit a phase-continuous carrier tone
            idx = np.arange(frames)
            ph = phase + dphase * idx
            outdata[:, 0] = 0.2 * np.sin(ph)
            phase = float((phase + dphase * frames) % (2 * math.pi))
            # analyze the mic return
            mic = indata[:, 0]
            if mic.shape[0] >= self.block:
                seg = mic[-self.block:] * window
                spec = np.abs(np.fft.rfft(seg)) ** 2
                u = float(spec[up].sum())
                d = float(spec[lo].sum())
                val = 100.0 * (u - d) / (u + d + 1e-9)  # signed sideband imbalance
                try:
                    q.put_nowait((time.time(), val))
                except queue.Full:
                    pass

        with sd.Stream(samplerate=sr, blocksize=self.block, channels=1,
                       dtype="float32", callback=callback):
            while True:
                yield q.get()


class SyntheticSonarSource:
    """No-hardware Doppler scene: quiet ~0, breathing ripple, walking excursions."""

    name = "sonar-sim"

    def __init__(self, hz: float = 20.0, breath_bpm: float = 15.0, seed=None):
        self.hz = hz
        self.breath_hz = breath_bpm / 60.0
        self.rng = random.Random(seed)
        self.backend = "simulated Doppler"

    def _raw(self) -> Iterator[Sample]:
        t, dt = 0.0, 1.0 / self.hz
        while True:
            phase = t % 40.0
            val = self.rng.gauss(0, 1.2)                     # sensor noise around 0
            if 8.0 <= phase < 22.0:                          # still: breathing Doppler
                val += 6.0 * math.sin(2 * math.pi * self.breath_hz * t)
            elif 24.0 <= phase < 34.0:                       # walking: approach then recede
                sweep = (phase - 24.0) / 10.0
                val += 40.0 * math.sin(2 * math.pi * 0.6 * t) * (1 - abs(2 * sweep - 1))
            yield 0.0, val
            t += dt

    def samples(self) -> Iterator[Sample]:
        return paced(self._raw(), self.hz)
