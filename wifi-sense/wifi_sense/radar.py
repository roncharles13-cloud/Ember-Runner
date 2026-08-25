"""RF device radar — light up nearby BLE-advertising devices.

This is NOT acoustic sonar and NOT the room-sensing scalar pipeline. It is a
passive listener for the Bluetooth-LE advertisements that phones, watches,
earbuds, and beacons broadcast constantly. Each advertising device becomes a
blip; Apple devices are flagged by their company-ID beacon (the same signal the
AirDrop/Continuity UI keys off).

Honest, deliberate limits — this tool respects them and does not try to defeat
them:

  * PRESENCE, NOT IDENTITY. iOS/Android randomize the advertised MAC address
    roughly every 15 minutes, so a device's id here is ephemeral. You see "a
    device is near", never "this is person X", and you cannot persistently track
    someone across time. We do not attempt to correlate rotations or de-anonymize.
  * DISTANCE, NOT DIRECTION. A single antenna yields RSSI (~coarse range) but no
    bearing. The dashboard places blips at an arbitrary, stable-per-id angle and
    says so.
  * ONLY WHAT'S ADVERTISING. A device shows up only while actively broadcasting.

Output is a periodic *snapshot*: the list of devices currently heard, each with a
short ephemeral id, RSSI, kind (apple / ble), advertised name if any, and age.

Real scanning needs `bleak` + a Bluetooth adapter. `radar-sim` needs nothing.
"""

from __future__ import annotations

import hashlib
import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

APPLE_COMPANY_ID = 0x004C
STALE_SEC = 12.0        # drop a device this long after we last heard it

# Apple "Continuity" advertisement type byte -> coarse DEVICE CATEGORY.
# This is device *kind*, never a person: we never decode the payload that
# follows (no hashed contact identifiers, no owner resolution, no tracking).
_APPLE_TYPE = {
    0x02: "beacon",   # iBeacon
    0x05: "phone",    # AirDrop (an active iOS device)
    0x07: "airpods",  # Proximity Pairing (AirPods / Beats)
    0x0C: "phone",    # Handoff
    0x10: "phone",    # Nearby (active iPhone/iPad)
    0x12: "findmy",   # Find My / offline finding beacon
}


def short_id(address: str) -> str:
    """Ephemeral, non-reversible short tag for a (already-random) address."""
    return hashlib.sha1(address.encode()).hexdigest()[:6]


def classify(kind: str, apple_bytes, name: str) -> str:
    """Coarse device *category* from the advertisement. Never an identity."""
    n = (name or "").lower()
    if "watch" in n:
        return "watch"
    if "airpod" in n or "buds" in n or "beats" in n or "headphone" in n:
        return "airpods"
    if "tile" in n or "airtag" in n:
        return "tag"
    if kind == "apple" and apple_bytes:
        return _APPLE_TYPE.get(apple_bytes[0], "apple")
    return "apple" if kind == "apple" else "ble"


@dataclass
class Device:
    id: str
    rssi: float
    kind: str            # "apple" | "ble"
    name: str
    first_seen: float
    last_seen: float
    category: str = "ble"

    def as_dict(self, now: float) -> dict:
        return {"id": self.id, "rssi": round(self.rssi, 1), "kind": self.kind,
                "category": self.category, "name": self.name,
                "age": round(now - self.last_seen, 1),
                "held": round(now - self.first_seen, 1)}


class SyntheticRadarScanner:
    """No-hardware demo: a shifting cast of nearby devices coming and going."""

    name = "radar-sim"

    def __init__(self, hz: float = 2.0, seed=None):
        self.hz = hz
        self.rng = random.Random(seed)
        # a pool of would-be neighbours; each drifts in RSSI and blinks in/out
        self._pool = []
        cast = [("apple", "phone", ""), ("apple", "airpods", "AirPods Pro"),
                ("apple", "phone", ""), ("apple", "watch", "Apple Watch"),
                ("apple", "findmy", ""), ("ble", "tag", "Tile"),
                ("ble", "ble", ""), ("apple", "phone", "")]
        for i, (kind, cat, name) in enumerate(cast):
            self._pool.append({
                "id": short_id(f"sim-{i}-{self.rng.random()}"),
                "kind": kind, "category": cat, "name": name,
                "rssi": self.rng.uniform(-90, -45),
                "present": self.rng.random() < 0.6,
                "vel": self.rng.uniform(-0.6, 0.6),   # rssi drift bias = motion
                "first": time.time(),
            })

    def snapshots(self) -> Iterator[list]:
        period = 1.0 / self.hz
        while True:
            now = time.time()
            devs = []
            for d in self._pool:
                # blink presence
                if self.rng.random() < 0.03:
                    d["present"] = not d["present"]
                    if d["present"]:
                        d["first"] = now
                if not d["present"]:
                    continue
                # random walk RSSI with a slow drift bias = the device moving
                if self.rng.random() < 0.02:
                    d["vel"] = self.rng.uniform(-0.6, 0.6)
                d["rssi"] = max(-98, min(-38, d["rssi"] + d["vel"] + self.rng.gauss(0, 0.8)))
                devs.append(Device(d["id"], d["rssi"], d["kind"], d["name"],
                                   d["first"], now, d["category"]).as_dict(now))
            yield devs
            time.sleep(period)


class BLERadarScanner:
    """Live passive BLE advertisement scanner via bleak."""

    name = "radar"

    def __init__(self, hz: float = 2.0):
        self.hz = hz
        self._devices: dict[str, Device] = {}
        self._lock = threading.Lock()
        try:
            import bleak  # noqa: F401
        except Exception as e:
            raise RuntimeError(
                "the RF radar needs the 'bleak' package and a Bluetooth adapter.\n"
                "  pip install bleak\n"
                "Grant Bluetooth permission, or use --source radar-sim for a demo."
            ) from e

    def _scanner_thread(self):
        import asyncio
        from bleak import BleakScanner

        def cb(device, adv):
            rssi = adv.rssi if adv.rssi is not None else getattr(device, "rssi", None)
            if rssi is None:
                return
            mfg = adv.manufacturer_data or {}
            kind = "apple" if APPLE_COMPANY_ID in mfg else "ble"
            name = adv.local_name or getattr(device, "name", None) or ""
            category = classify(kind, mfg.get(APPLE_COMPANY_ID), name)
            sid = short_id(device.address)
            now = time.time()
            with self._lock:
                d = self._devices.get(sid)
                if d is None:
                    self._devices[sid] = Device(sid, float(rssi), kind,
                                                name or "", now, now, category)
                else:
                    d.rssi = float(rssi)
                    d.kind = kind
                    d.category = category
                    if name:
                        d.name = name
                    d.last_seen = now

        async def main():
            scanner = BleakScanner(detection_callback=cb)
            await scanner.start()
            while True:
                await asyncio.sleep(3600)

        asyncio.new_event_loop().run_until_complete(main())

    def snapshots(self) -> Iterator[list]:
        threading.Thread(target=self._scanner_thread, daemon=True).start()
        period = 1.0 / self.hz
        while True:
            now = time.time()
            with self._lock:
                stale = [k for k, d in self._devices.items()
                         if now - d.last_seen > STALE_SEC]
                for k in stale:
                    del self._devices[k]
                snap = [d.as_dict(now) for d in self._devices.values()]
            snap.sort(key=lambda x: x["rssi"], reverse=True)
            yield snap
            time.sleep(period)


def make_scanner(kind: str, **kw):
    if kind == "radar":
        return BLERadarScanner(hz=kw.get("hz", 2.0))
    if kind == "radar-sim":
        return SyntheticRadarScanner(hz=kw.get("hz", 2.0), seed=kw.get("seed"))
    raise ValueError(f"not a radar kind: {kind!r}")


# -- server ---------------------------------------------------------------

class _ScanThread(threading.Thread):
    def __init__(self, scanner, hub):
        super().__init__(daemon=True)
        self.scanner = scanner
        self.hub = hub

    def run(self):
        for snap in self.scanner.snapshots():
            self.hub.publish({"devices": snap, "t": time.time()})


def serve_radar(scanner, host: str, port: int) -> None:
    """Serve the radar dashboard + an SSE stream of device snapshots."""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    from .server import Hub

    static = Path(__file__).parent / "static"
    hub = Hub(history=1)
    _ScanThread(scanner, hub).start()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/stream":
                return self._stream()
            if path == "/meta":
                body = json.dumps({"mode": "radar", "source": scanner.name}).encode()
                self._send(body, "application/json")
                return
            if path in ("/", "/index.html", "/radar.html"):
                fp = static / "radar.html"
                self._send(fp.read_bytes(), "text/html; charset=utf-8")
                return
            self.send_error(404)

        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream(self):
            q, _ = hub.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = q.get()
                    self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
    print(f"\n  WiFi-Sense RF radar  ->  {url}")
    print(f"  source: {scanner.name}   (passive BLE · presence not identity · Ctrl-C to stop)\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        httpd.shutdown()
