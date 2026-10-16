"""Raspberry Pi side of the Bluetooth link: take (or load) 3-5 trunk photos and send
them to the backend computer, then print the identification it sends back.

    # photos already on disk
    hemlock-bt-send --address AA:BB:CC:DD:EE:FF photo1.jpg photo2.jpg photo3.jpg --severity 1
    # take them with the Pi camera (press Enter at each position around the tree)
    hemlock-bt-send --address AA:BB:CC:DD:EE:FF --camera 3 --lat 34.83 --lon -85.48
    # over Wi-Fi instead of Bluetooth
    hemlock-bt-send --tcp 192.168.1.20:9000 photo1.jpg photo2.jpg photo3.jpg

Needs only the Python standard library (plus picamera2 for --camera, preinstalled
on Raspberry Pi OS). The heavy model runs on the receiving computer.
"""

from __future__ import annotations

import argparse
import io
import json
import socket
import sys
from pathlib import Path

from .protocol import recv_message, rfcomm_socket, send_message

POSITIONS = ["NORTH side of the trunk, bark at chest height",
             "a quarter-turn clockwise, bark at chest height",
             "another quarter-turn clockwise, bark at chest height",
             "the last quarter-turn (west side)",
             "back on the north side, bark at head height"]


def take_photos(n: int) -> list[bytes]:
    try:
        from picamera2 import Picamera2
    except ImportError:
        raise SystemExit("--camera needs picamera2 (Raspberry Pi OS: sudo apt install python3-picamera2)") from None
    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={"size": (2028, 1520)}))
    cam.start()
    out = []
    try:
        for i in range(n):
            input(f"[{i + 1}/{n}] Stand 1 m from the tree, {POSITIONS[i]}. Press Enter to capture...")
            buf = io.BytesIO()
            cam.capture_file(buf, format="jpeg")
            out.append(buf.getvalue())
            print(f"      captured {len(out[-1]) // 1024} KB")
    finally:
        cam.stop()
    return out


def connect(args) -> socket.socket:
    if args.tcp:
        host, port = args.tcp.rsplit(":", 1)
        return socket.create_connection((host, int(port)), timeout=args.timeout)
    s = rfcomm_socket()
    s.settimeout(args.timeout)
    s.connect((args.address, args.channel))
    return s


def send_capture(sock: socket.socket, photos: list[bytes], meta: dict) -> dict:
    send_message(sock, {"type": "capture", **{k: v for k, v in meta.items() if v is not None}}, photos)
    reply, _ = recv_message(sock)
    return reply


def describe(reply: dict) -> str:
    if not reply.get("ok"):
        e = reply.get("error", {})
        return f"ERROR {e.get('code')}: {e.get('message')}"
    r = reply["result"]
    sp = r.get("species") or {}
    lines = [f"{sp.get('name', 'unknown species')} ({sp.get('confidence', 0):.0%})" if sp else "species: -"]
    if r["status"] == "existing":
        lines.append(f"Existing tree {r['tree_id']} (p={r.get('probability', 0):.2f})")
    elif r["status"] == "new":
        lines.append(f"New tree registered as {r['tree_id']}")
    elif r["status"] == "uncertain":
        lines.append("Uncertain: review in the app. Candidates: "
                     + ", ".join(c["tree_id"] for c in r.get("candidates", [])))
    else:
        lines.append(r.get("message", r["status"]))
    bad = [v for v in r.get("views", []) if not v["accepted"]]
    for v in bad:
        lines.append(f"  photo {v['index'] + 1} rejected: {'; '.join(v['problems'])}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Send tree photos from the Pi to the backend over Bluetooth")
    ap.add_argument("photos", nargs="*", type=Path)
    ap.add_argument("--address", help="Bluetooth address of the computer running hemlock-bt-receiver")
    ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--tcp", metavar="HOST:PORT", help="use TCP (Wi-Fi) instead of Bluetooth")
    ap.add_argument("--camera", type=int, metavar="N", help="take N photos with the Pi camera (3-5)")
    ap.add_argument("--forest", type=int, help="forest id (default: the receiver's)")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--accuracy-m", type=float)
    ap.add_argument("--severity", type=int, choices=[0, 1, 2, 3], help="0 none, 1 light, 2 moderate, 3 severe")
    ap.add_argument("--notes")
    ap.add_argument("--ping", action="store_true", help="only check the link")
    ap.add_argument("--json", action="store_true", help="print the raw result")
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    if not args.tcp and not args.address:
        ap.error("give --address (Bluetooth) or --tcp HOST:PORT")
    with connect(args) as sock:
        if args.ping:
            send_message(sock, {"type": "ping"})
            print("link OK" if recv_message(sock)[0].get("type") == "pong" else "unexpected reply")
            return
        photos = take_photos(args.camera) if args.camera else [p.read_bytes() for p in args.photos]
        if not 3 <= len(photos) <= 7:
            ap.error("need 3-7 photos")
        print(f"sending {len(photos)} photos ({sum(map(len, photos)) // 1024} KB)...")
        reply = send_capture(sock, photos, {"forest_id": args.forest, "lat": args.lat, "lon": args.lon,
                                            "accuracy_m": args.accuracy_m, "severity": args.severity,
                                            "health_notes": args.notes})
    print(json.dumps(reply, indent=1) if args.json else describe(reply))
    sys.exit(0 if reply.get("ok") else 1)


if __name__ == "__main__":
    main()
