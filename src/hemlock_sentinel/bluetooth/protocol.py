"""Wire format between the Raspberry Pi and the backend over a Bluetooth RFCOMM
(serial-port-like) stream. Works unchanged over TCP, which is used for tests and
when the Pi is on the same Wi-Fi.

One message =
    b"HSBT" | version (1 byte) | header length (4 bytes, big-endian) | header (UTF-8 JSON)
    | for each entry of header["blob_sizes"]: that many raw bytes (photos, JPEG)

Requests (Pi -> backend):  {"type": "ping"}
                           {"type": "capture", "forest_id": 3?, "view_keys": [...]?, "headings": [...]?,
                            "lat": .., "lon": .., "accuracy_m": .., "severity": 0-3?, "health_notes": ""?}
                           + 3-7 photos
Responses (backend -> Pi): {"type": "pong"} | {"type": "result", "ok": true, "result": {...API result...}}
                           | {"type": "result", "ok": false, "error": {"code": .., "message": ..}}
"""

from __future__ import annotations

import json
import socket
import struct

MAGIC = b"HSBT"
VERSION = 1
MAX_HEADER = 64 * 1024
MAX_BLOB = 25_000_000
MAX_BLOBS = 8


class ProtocolError(Exception):
    pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), 1 << 16))
        if not chunk:
            raise ConnectionError("connection closed mid-message" if buf else "connection closed")
        buf += chunk
    return bytes(buf)


def send_message(sock: socket.socket, header: dict, blobs: list[bytes] = ()) -> None:
    if len(blobs) > MAX_BLOBS or any(len(b) > MAX_BLOB for b in blobs):
        raise ProtocolError(f"at most {MAX_BLOBS} photos of {MAX_BLOB // 1_000_000} MB each")
    h = json.dumps({**header, "blob_sizes": [len(b) for b in blobs]}).encode()
    if len(h) > MAX_HEADER:
        raise ProtocolError("header too large")
    sock.sendall(MAGIC + bytes([VERSION]) + struct.pack(">I", len(h)) + h)
    for b in blobs:
        sock.sendall(b)


def recv_message(sock: socket.socket) -> tuple[dict, list[bytes]]:
    pre = _recv_exact(sock, 9)
    if pre[:4] != MAGIC:
        raise ProtocolError("not a Hemlock Sentinel message")
    if pre[4] != VERSION:
        raise ProtocolError(f"unsupported protocol version {pre[4]}")
    (hlen,) = struct.unpack(">I", pre[5:9])
    if hlen > MAX_HEADER:
        raise ProtocolError("header too large")
    try:
        header = json.loads(_recv_exact(sock, hlen))
    except ValueError as e:
        raise ProtocolError("header is not JSON") from e
    sizes = header.pop("blob_sizes", [])
    if not isinstance(sizes, list) or len(sizes) > MAX_BLOBS or any(
            not isinstance(s, int) or not 0 <= s <= MAX_BLOB for s in sizes):
        raise ProtocolError("bad blob sizes")
    return header, [_recv_exact(sock, s) for s in sizes]


def rfcomm_available() -> bool:
    return hasattr(socket, "AF_BLUETOOTH") and hasattr(socket, "BTPROTO_RFCOMM")


def rfcomm_socket() -> socket.socket:
    if not rfcomm_available():
        raise SystemExit("this Python has no Bluetooth RFCOMM support (Linux/Raspberry Pi OS have it); "
                         "use --tcp instead")
    return socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
