"""Command-line entry point.

    python -m wifi_sense                      # live capture from your WiFi card
    python -m wifi_sense --source synthetic   # no hardware, scripted demo
    python -m wifi_sense --source replay --file cap.csv
    python -m wifi_sense --record cap.csv      # live + save raw RSSI to CSV
"""

from __future__ import annotations

import argparse
import sys

from .dsp import SenseEngine
from .server import Recorder, serve
from .sources import make_source


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="wifi_sense",
                                description="Laptop-only WiFi sensing (RSSI tier).")
    p.add_argument("--source", choices=["rssi", "synthetic", "replay"],
                   default="rssi", help="signal source (default: rssi)")
    p.add_argument("--file", help="CSV file for --source replay")
    p.add_argument("--loop", action="store_true", help="loop the replay file")
    p.add_argument("--hz", type=float, default=20.0,
                   help="target sample rate (default: 20)")
    p.add_argument("--record", metavar="CSV",
                   help="save raw RSSI to a CSV while running")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=87 * 100 + 65)  # 8765
    p.add_argument("--window", type=float, default=30.0,
                   help="analysis window seconds (default: 30)")
    args = p.parse_args(argv)

    if args.source == "replay" and not args.file:
        p.error("--source replay requires --file")

    try:
        source = make_source(
            args.source, hz=args.hz,
            path=args.file, loop=args.loop,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    engine = SenseEngine(window_sec=args.window)
    recorder = Recorder(args.record) if args.record else None
    serve(source, engine, args.host, args.port, recorder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
