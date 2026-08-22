# WiFi-Sense (RSSI tier)

Laptop-only WiFi sensing you can run **today, on any PC, with no extra
hardware**. It reads how your body perturbs the radio link to your router and
turns that into a live browser dashboard showing **presence**, **motion**, and a
(marginal) **breathing rate** — plus a synthetic mode so you can watch the whole
thing work before you ever touch real signals.

```
python -m wifi_sense --source synthetic   # no hardware — scripted demo
python -m wifi_sense                       # live, from your laptop's WiFi card
```
Then open the URL it prints (default <http://127.0.0.1:8765>).

---

## Be honest about what this can and can't do

WiFi sensing is a real field (MIT's RF-Pose/WiTrack, CSI activity recognition).
Bodies perturb the radio channel, and you can read that perturbation. **But what
you can extract depends entirely on what your radio exposes**, and a normal
laptop only hands you **one number per sample: RSSI** (received signal strength).
It does **not** give you CSI (per-subcarrier amplitude & phase), which is what
the impressive pose/silhouette demos require.

So this project is deliberately organized as **tiers**, and ships tier 1:

| Tier | Hardware | Signal | Honestly gives you |
|------|----------|--------|--------------------|
| **1 (this)** | any laptop | RSSI (1 scalar/sample) | presence ✅, motion ✅, breathing ⚠️ (close & still only) |
| 2 | ESP32 (~$5) | real CSI, 1 antenna | robust breathing, gesture-scale motion |
| 3 | Nexmon (RPi/AX210) or PicoScenes | multi-antenna CSI | coarse pose/localization, the "real" demos |

Tier 1 is **not** going to image a room or see through walls. What it *will* do:
reliably tell you when someone walks through the link, hold a "present" state
while they're around, and — when someone sits still near the router — pick their
breathing frequency out of the noise. That's genuinely useful (occupancy,
presence automation, a breathing spot-check) and it's real, not a toy.

The code is structured so **moving up a tier is a one-file change**: everything
downstream of `sources/` (DSP, server, dashboard) is signal-agnostic. Drop in a
CSI source that emits richer samples and the rest keeps working.

---

## Install & run

```bash
cd wifi-sense
pip install -r requirements.txt        # just numpy

# 1) see it work with zero hardware
python -m wifi_sense --source synthetic

# 2) go live off your own WiFi card
python -m wifi_sense

# 3) record a capture, then replay it later
python -m wifi_sense --record capture.csv
python -m wifi_sense --source replay --file capture.csv --loop
```

Open the printed URL in a browser for the live dashboard.

### Getting a usable live signal

RSSI sensing works best when **your body actually sits between the laptop and the
router**. Put the laptop a few meters from the AP, then walk across the line
between them — you'll see the trace jump and **PRESENT** light up. For the
breathing test, sit still ~1–2 m from the router with a clear line to it; give it
20–30 s to fill the analysis window. Low breathing confidence is normal and is
reported honestly rather than hidden.

---

## How it works

```
 WiFi card ──► sources/rssi.py ──► dsp.SenseEngine ──► server (SSE) ──► browser
 (RSSI dBm)     platform poll        detrend + FFT       fan-out         dashboard
```

- **Capture** (`sources/rssi.py`): polls the OS for current link RSSI — Linux
  `/proc/net/wireless` (no sudo) or `iw`; macOS `airport`/`wdutil`; Windows
  `netsh`. Auto-selected per platform.
- **DSP** (`dsp.py`): moving-average high-pass to kill router-power drift; RMS of
  the residual gives a self-calibrating **motion** energy; hysteresis + hold
  turns that into **presence**; a Hann-windowed FFT finds the dominant peak in
  the 0.10–0.60 Hz **breathing** band and reports a confidence from how much that
  peak stands out.
- **Serve** (`server.py`): stdlib `http.server` streams results to the browser
  over **Server-Sent Events** — that's why the only dependency is numpy.

---

## Platform notes

- **Linux** — works unprivileged via `/proc/net/wireless`. If empty, install
  `iw` (`sudo apt install iw`). RSSI refresh is driver-dependent.
- **macOS** — `airport -I` works on many versions; newer releases deprecate it
  and fall back to `wdutil info`, which may need `sudo`.
- **Windows** — `netsh wlan show interfaces` reports link quality as a
  percentage, mapped to approximate dBm. Coarser than the others.

If no backend works (e.g. not associated to an AP), the CLI says so and you can
always fall back to `--source synthetic`.

---

## Layout

```
wifi-sense/
  wifi_sense/
    __main__.py        CLI
    dsp.py             SenseEngine — motion / presence / breathing
    server.py          SSE dashboard server + capture thread + recorder
    sources/
      base.py          Source protocol (where a CSI adapter plugs in)
      rssi.py          live capture, cross-platform
      synthetic.py     scripted no-hardware demo
      replay.py        replay a recorded CSV
    static/index.html  the live dashboard
  tests/test_dsp.py
  requirements.txt
```

## Roadmap to real CSI (tier 2+)

Add `sources/esp32_csi.py` that reads CSI frames from an ESP32 (running the
`esp-csi` firmware) over serial/UDP and emits per-subcarrier samples, then extend
`SenseEngine` to consume the subcarrier matrix. No change needed to the server or
dashboard transport. This is the path from "presence & breathing" to real
motion-fingerprinting and coarse localization.
