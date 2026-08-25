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
from .features import FeatureEngine
from .server import Recorder, serve
from .sources import make_source


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="wifi_sense",
                                description="Laptop-only WiFi sensing (RSSI tier).")
    from .sources import KINDS
    radar_kinds = ["radar", "radar-sim"]
    all_kinds = KINDS + radar_kinds
    p.add_argument("--source", choices=all_kinds, default="rssi",
                   metavar="SRC",
                   help="signal source: " + ", ".join(KINDS)
                        + "; or RF device radar: " + ", ".join(radar_kinds)
                        + " (default: rssi)")
    p.add_argument("--file", help="CSV file for --source replay")
    p.add_argument("--loop", action="store_true", help="loop the replay file")
    p.add_argument("--ble-address", help="target BLE device address for --source ble")
    p.add_argument("--udp-port", type=int, default=9099,
                   help="UDP port for --source lidar depth stream (default: 9099)")
    p.add_argument("--hz", type=float, default=20.0,
                   help="target sample rate (default: 20)")
    p.add_argument("--record", metavar="CSV",
                   help="save raw RSSI to a CSV while running")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=87 * 100 + 65)  # 8765
    p.add_argument("--window", type=float, default=30.0,
                   help="analysis window seconds (default: 30)")
    p.add_argument("--no-features", action="store_true",
                   help="disable spectrogram + delay-embedding features")
    args = p.parse_args(argv)

    if args.source == "replay" and not args.file:
        p.error("--source replay requires --file")

    # RF device radar is a different mode (device snapshots, not a scalar stream)
    if args.source in radar_kinds:
        from .radar import make_scanner, serve_radar
        try:
            scanner = make_scanner(args.source, hz=args.hz)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        serve_radar(scanner, args.host, args.port)
        return 0

    try:
        source = make_source(
            args.source, hz=args.hz,
            path=args.file, loop=args.loop,
            address=args.ble_address, port=args.udp_port,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    engine = SenseEngine(window_sec=args.window)
    features = None if args.no_features else FeatureEngine()
    recorder = Recorder(args.record) if args.record else None
    serve(source, engine, args.host, args.port, recorder, features)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
