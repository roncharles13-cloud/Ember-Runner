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

### View it on your phone

The sensing runs on this computer; your phone is just the screen — no app, nothing
installed, nothing changed on the phone. Add `--lan` and open the printed URL on a
phone on the **same Wi-Fi**:

```
python -m wifi_sense --source radar-sim --lan
#   this device:  http://localhost:8765
#   your phone:   http://192.168.x.y:8765   (same Wi-Fi; allow the firewall prompt)
```

This works for every mode, including the RF radar. Note the phone *displays* the
radar — it can't scan BLE itself (browsers can't, and iOS hides Apple beacons from
apps); the laptop does the scanning. Acoustic **sonar** is the one sensor that can
run natively in a phone browser (Web Audio + mic).

### Pocket Sonar — room sensing on the phone itself

`wifi_sense/static/sonar-phone.html` is a standalone page that turns the phone into
an active sonar: it plays an inaudible ~18 kHz tone through the speaker and reads the
Doppler-shifted echo off the mic, giving live **motion / presence / breathing** and a
Doppler scope — entirely on-device, no server and no one else's data. It needs mic
permission and a **secure (https) context**, so open it over https (e.g. published as
an artifact) or from `localhost`; plain `http://<lan-ip>` won't grant the mic. It
emits a faint tone (uses the speaker) and senses **motion, not identity**.

---

## Not just WiFi: one pipeline, many sensors

WiFi RSSI is only one way to feel a room, and honestly one of the weakest. Every
source below emits the **same 1-D perturbation stream**, so the DSP, spectrogram,
phase-portrait, and dashboard are identical no matter which sensor feeds them —
only the value's meaning changes. Each real sensor has a `-sim` twin that needs
no hardware, so you can see it work first.

| `--source` | Sensor | Value it emits | Needs |
|---|---|---|---|
| `rssi` | laptop WiFi card | signal strength (dBm) | nothing |
| `sonar` | speaker + mic | acoustic Doppler imbalance (~0 at rest) | `sounddevice` |
| `ble` | Bluetooth LE | advertiser RSSI (dBm) | `bleak` |
| `lidar` | iPhone/iPad Pro depth | measured range (metres) | UDP feed from the device |
| `sonar-sim` / `ble-sim` / `lidar-sim` | — | simulated versions of the above | nothing |

```
pip install -r requirements-sensors.txt     # only for the real sources

python -m wifi_sense --source sonar-sim      # inaudible-tone Doppler, no hardware
python -m wifi_sense --source sonar          # real: plays ~19 kHz, reads the mic
python -m wifi_sense --source ble            # track the strongest BLE advertiser
python -m wifi_sense --source ble --ble-address AA:BB:CC:DD:EE:FF
python -m wifi_sense --source lidar --udp-port 9099   # ingest iPhone depth
```

**Why sonar is the strong one:** we *emit* the probe (a ~19 kHz tone you can't
hear) instead of eavesdropping, so SNR is high and the sample rate is ~48 kHz.
Motion Doppler-shifts the echo; the sign even tells you *toward* vs *away*.

**LiDAR** is the only sensor here that also carries coarse depth/position, not
just "something moved" — but it's Pro-iPhone-only. Feed it by having a small
ARKit app or Shortcut stream the scene's average depth to this machine, one
reading per UDP datagram: a bare number in metres, or `{"range": 1.83}`.

---

## RF device radar — light up nearby phones

A different mode entirely (not the scalar room-sensing pipeline): a passive
listener for the Bluetooth-LE advertisements phones/watches/earbuds broadcast.
Each advertising device becomes a blip on a sweeping radar; Apple devices are
flagged by their company-ID beacon (the same signal AirDrop/Continuity uses).

```
python -m wifi_sense --source radar-sim   # animated demo, no hardware
python -m wifi_sense --source radar        # live BLE scan (needs bleak + adapter)
```

**Honest, enforced limits** — this deliberately does *not* try to defeat privacy:

- **Presence, not identity.** iOS/Android randomize the advertised MAC ~every 15
  min, so each device id is ephemeral. You see *a device*, never *who*, and can't
  track anyone over time. No rotation-correlation, no de-anonymization.
- **Distance, not direction.** One antenna gives RSSI (rough range) but no
  bearing, so blip angle is arbitrary (and labelled as such).
- **Only advertising devices** appear — a phone that isn't broadcasting is invisible.

This is a "what radios are broadcasting around me" scope, like any BLE scanner —
useful and legitimate, without crossing into tracking people.

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
