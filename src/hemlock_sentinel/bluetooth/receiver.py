"""Backend side of the Bluetooth link: receives photos from the Raspberry Pi and
runs them through the model by forwarding them to the running hemlock-api.

    hemlock-api &                                   # the backend
    hemlock-bt-receiver --email demo@hemlock.test --password hemlock-demo --forest 1
    hemlock-bt-receiver ... --tcp 9000              # same protocol over Wi-Fi / for testing

The receiver signs in once, then for every "capture" message from the Pi calls
POST /api/v1/identify and sends the result back over the same Bluetooth link,
so the Pi can show "H-017 (existing)" on its screen.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import threading
import urllib.error
import urllib.request
import uuid

from .protocol import ProtocolError, recv_message, rfcomm_socket, send_message

log = logging.getLogger("hemlock.bt")


class ApiClient:
    """Minimal stdlib HTTP client for the backend (no extra dependencies on the receiver)."""

    def __init__(self, base: str, email: str | None, password: str | None, timeout: float = 120):
        self.base = base.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.token = None
        if email:
            self.token = self._call("POST", "/auth/login", json.dumps({"email": email, "password": password}).encode(),
                                    "application/json")["token"]

    def _call(self, method: str, path: str, body: bytes | None = None, ctype: str | None = None,
              forest_id: int | None = None) -> dict:
        req = urllib.request.Request(self.base + path, data=body, method=method)
        req.add_header("Accept", "application/json")
        if ctype:
            req.add_header("Content-Type", ctype)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if forest_id is not None:
            req.add_header("X-Forest-Id", str(forest_id))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())["error"]
            except Exception:  # noqa: BLE001
                err = {"code": "http_error", "message": f"HTTP {e.code}"}
            raise ApiCallError(err) from e

    def identify(self, photos: list[bytes], fields: dict, forest_id: int | None) -> dict:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            if v is None:
                continue
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for i, p in enumerate(photos):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="images"; filename="pi{i}.jpg"\r\n'
                         f"Content-Type: image/jpeg\r\n\r\n".encode() + p + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        return self._call("POST", "/identify", body, f"multipart/form-data; boundary={boundary}", forest_id)


class ApiCallError(Exception):
    def __init__(self, error: dict):
        super().__init__(error.get("message"))
        self.error = error


def _form_fields(h: dict) -> dict:
    out = {k: h.get(k) for k in ("lat", "lon", "accuracy_m", "severity", "health_notes")}
    if h.get("view_keys"):
        out["view_keys"] = ",".join(h["view_keys"])
    if h.get("headings"):
        out["headings"] = ",".join("" if x is None else str(x) for x in h["headings"])
    return out


def handle_connection(conn: socket.socket, api: ApiClient, default_forest: int | None) -> None:
    with conn:
        while True:
            try:
                header, blobs = recv_message(conn)
            except ConnectionError:
                return
            except ProtocolError as e:
                send_message(conn, {"type": "result", "ok": False, "error": {"code": "protocol", "message": str(e)}})
                return
            kind = header.get("type")
            if kind == "ping":
                send_message(conn, {"type": "pong"})
                continue
            if kind != "capture":
                send_message(conn, {"type": "result", "ok": False,
                                    "error": {"code": "unknown_type", "message": f"unknown message type {kind!r}"}})
                continue
            forest = header.get("forest_id", default_forest)
            log.info("capture: %d photos, forest %s", len(blobs), forest)
            try:
                res = api.identify(blobs, _form_fields(header), forest)
                log.info(" -> %s %s", res.get("status"), res.get("tree_id"))
                send_message(conn, {"type": "result", "ok": True, "result": res})
            except ApiCallError as e:
                send_message(conn, {"type": "result", "ok": False, "error": e.error})
            except OSError as e:
                send_message(conn, {"type": "result", "ok": False,
                                    "error": {"code": "backend_unreachable", "message": str(e)}})


def serve(server: socket.socket, api: ApiClient, default_forest: int | None, stop: threading.Event | None = None):
    server.listen(2)
    while stop is None or not stop.is_set():
        try:
            conn, addr = server.accept()
        except OSError:
            if stop is not None and stop.is_set():
                return
            raise
        log.info("connected: %s", addr)
        threading.Thread(target=handle_connection, args=(conn, api, default_forest), daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser(description="Receive photos from the Raspberry Pi over Bluetooth")
    ap.add_argument("--api", default="http://localhost:8000", help="running hemlock-api")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--forest", type=int, help="default forest id (the Pi may override per capture)")
    ap.add_argument("--channel", type=int, default=1, help="RFCOMM channel (Pi must use the same)")
    ap.add_argument("--adapter", default="00:00:00:00:00:00", help="local Bluetooth adapter address (any)")
    ap.add_argument("--tcp", type=int, metavar="PORT", help="listen on TCP instead of Bluetooth")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    api = ApiClient(args.api, args.email, args.password)
    if args.tcp:
        server = socket.create_server(("0.0.0.0", args.tcp))
        where = f"TCP port {args.tcp}"
    else:
        server = rfcomm_socket()
        server.bind((args.adapter, args.channel))
        where = f"Bluetooth RFCOMM channel {args.channel}"
    log.info("waiting for the Pi on %s (backend %s, forest %s)", where, args.api, args.forest)
    try:
        serve(server, api, args.forest)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    main()
