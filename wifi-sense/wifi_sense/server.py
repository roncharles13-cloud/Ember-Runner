"""Live dashboard server.

One stdlib HTTP server does two jobs:
  GET /            -> the dashboard page (static/index.html)
  GET /stream      -> a Server-Sent Events stream of live SenseResults

SSE (not WebSocket) keeps the whole toolkit at a single third-party dependency
(numpy). A background thread pulls samples from the chosen Source, runs them
through SenseEngine, and fan-outs each result to every connected browser.
"""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .dsp import SenseEngine, SenseResult
from .features import FMAX_HZ, NBINS, FeatureEngine

STATIC = Path(__file__).parent / "static"


class Hub:
    """Fan-out of results to connected SSE clients."""

    def __init__(self, history: int = 600):
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._history_max = history

    def publish(self, payload: dict) -> None:
        with self._lock:
            self._history.append(payload)
            if len(self._history) > self._history_max:
                self._history.pop(0)
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.discard(q)

    def subscribe(self) -> tuple[queue.Queue, list[dict]]:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._clients.add(q)
            backlog = list(self._history)
        return q, backlog

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)


def _result_to_payload(r: SenseResult) -> dict:
    d = asdict(r)
    # round for compact transport
    d["rssi"] = round(d["rssi"], 1)
    d["motion"] = round(d["motion"], 3)
    d["fs"] = round(d["fs"], 2)
    if d["breathing_bpm"] is not None:
        d["breathing_bpm"] = round(d["breathing_bpm"], 1)
    d["breathing_conf"] = round(d["breathing_conf"], 2)
    return d


class CaptureThread(threading.Thread):
    """Reads the source, runs DSP, publishes to the hub."""

    def __init__(self, source, engine: SenseEngine, hub: Hub,
                 recorder: Optional["Recorder"] = None,
                 features: Optional[FeatureEngine] = None):
        super().__init__(daemon=True)
        self.source = source
        self.engine = engine
        self.features = features
        self.hub = hub
        self.recorder = recorder
        self._stop = threading.Event()

    def run(self) -> None:
        for t, rssi in self.source.samples():
            if self._stop.is_set():
                break
            if self.recorder:
                self.recorder.write(t, rssi)
            payload = _result_to_payload(self.engine.add(rssi, t))
            if self.features is not None:
                f = self.features.add(rssi, t)
                payload["spec"] = f.spec
                payload["bands"] = f.bands
                payload["embed"] = f.embed
                payload["tau"] = f.tau
            self.hub.publish(payload)

    def stop(self) -> None:
        self._stop.set()


class Recorder:
    """Appends raw (timestamp,rssi) rows to a CSV for later --source replay."""

    def __init__(self, path: str):
        self._f = open(path, "w", buffering=1)
        self._f.write("timestamp,rssi\n")

    def write(self, t: float, rssi: float) -> None:
        self._f.write(f"{t:.4f},{rssi:.2f}\n")

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass


def make_handler(hub: Hub, meta: dict):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet
            pass

        def do_GET(self):
            if self.path.split("?")[0] == "/stream":
                return self._stream()
            if self.path in ("/", "/index.html"):
                return self._file("index.html", "text/html; charset=utf-8")
            if self.path == "/meta":
                return self._json(meta)
            self.send_error(404)

        def _file(self, name: str, ctype: str):
            fp = STATIC / name
            if not fp.exists():
                return self.send_error(404)
            body = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream(self):
            q, backlog = hub.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                if backlog:
                    self._sse({"type": "backlog", "items": backlog})
                while True:
                    payload = q.get()
                    self._sse({"type": "sample", **payload})
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

        def _sse(self, obj: dict):
            data = "data: " + json.dumps(obj) + "\n\n"
            self.wfile.write(data.encode())
            self.wfile.flush()

    return Handler


def serve(source, engine: SenseEngine, host: str, port: int,
          recorder: Optional[Recorder] = None,
          features: Optional[FeatureEngine] = None) -> None:
    hub = Hub()
    meta = {"source": source.name,
            "backend": getattr(source, "backend", None),
            "features": features is not None,
            "fmax": FMAX_HZ if features else None,
            "nbins": NBINS if features else None}
    cap = CaptureThread(source, engine, hub, recorder, features)
    cap.start()
    httpd = ThreadingHTTPServer((host, port), make_handler(hub, meta))
    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
    print(f"\n  WiFi-Sense dashboard  ->  {url}")
    print(f"  source: {source.name}"
          + (f" ({source.backend})" if getattr(source, 'backend', None) else "")
          + "   (Ctrl-C to stop)\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        cap.stop()
        httpd.shutdown()
        if recorder:
            recorder.close()
