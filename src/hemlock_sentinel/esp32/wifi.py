"""The ESP32 node's Wi-Fi API (firmware/esp32_wifi_node): a client, and a simulated node.

The node is its own Wi-Fi access point (``HS-ESP32-xxxx``) and serves JSON at http://192.168.4.1:

    GET  /api/v1/status            device, firmware, uptime, simulated, clients, log size
    GET  /api/v1/reading           latest reading
    POST /api/v1/measure           measure now, return the reading
    GET  /api/v1/readings?since=N  logged readings with seq > N (oldest first, 50 per page)

``SimulatedNode`` serves the same API from a computer, so the phone app and tests can run without the
board: ``hemlock-esp32 simulate`` then pair the app with http://<computer-ip>:8090.
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .reading import BadReading, parse_reading

DEFAULT_URL = "http://192.168.4.1"
PAGE_MAX = 50


class NodeError(RuntimeError):
    pass


class WifiNode:
    """Client for one node. ``base``: e.g. http://192.168.4.1 (the node's own network)."""

    def __init__(self, base: str = DEFAULT_URL, timeout: float = 6.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str) -> dict:
        req = urllib.request.Request(self.base + path, method=method, data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read())["error"]["message"]
            except Exception:  # noqa: BLE001
                msg = str(e)
            raise NodeError(f"{method} {path}: HTTP {e.code}: {msg}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise NodeError(f"cannot reach the sensor node at {self.base} (joined its Wi-Fi HS-ESP32-xxxx?): "
                            f"{getattr(e, 'reason', e)}") from None

    def status(self) -> dict:
        return self._call("GET", "/api/v1/status")

    def reading(self) -> dict:
        """Latest reading, parsed like every other path: {"device", "sensors", "raw"}."""
        return parse_reading(json.dumps(self._call("GET", "/api/v1/reading")))

    def measure(self) -> dict:
        return parse_reading(json.dumps(self._call("POST", "/api/v1/measure")))

    def readings(self, since: int = 0) -> list[dict]:
        """Every logged reading after ``since`` (follows pages), each parsed."""
        out = []
        while True:
            page = self._call("GET", f"/api/v1/readings?since={since}")
            for r in page["readings"]:
                try:
                    out.append(parse_reading(json.dumps(r)))
                except BadReading:
                    continue
                since = max(since, int(r["seq"]))
            if not page.get("more"):
                return out


# ------------------------------------------------------------------ simulated node
class SimulatedNode:
    """The firmware's HTTP API, served from Python (same JSON). Values drift like sensors.h's simulation."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8090, device: str = "HS-ESP32-SIM0",
                 log_every_s: float = 60.0, seed: int | None = None):
        self.device = device
        self.log_every_s = log_every_s
        self._rng = random.Random(seed)
        self._v = {"soil_moisture_pct": 34.0, "air_temp_c": 18.0, "humidity_pct": 70.0, "light_lux": 6000.0}
        self._t0 = time.monotonic()
        self._seq = 0
        self._latest: dict | None = None
        self._log: list[dict] = []
        self._last_log = -1e9
        self._lock = threading.Lock()
        node = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _send(self, code: int, body: dict | str, ctype: str = "application/json"):
                data = (json.dumps(body, separators=(",", ":")) if isinstance(body, dict) else body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _err(self, code: int, err: str, msg: str):
                self._send(code, {"error": {"code": err, "message": msg}})

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/":
                    return self._send(200, f"{node.device} (simulated Hemlock Sentinel sensor node)\n", "text/plain")
                if u.path == "/api/v1/status":
                    return self._send(200, node.status())
                if u.path == "/api/v1/reading":
                    return self._send(200, node.latest())
                if u.path == "/api/v1/readings":
                    since = parse_qs(u.query).get("since", ["0"])[0]
                    if not since.isdigit():
                        return self._err(400, "bad_since", "since must be a whole number")
                    return self._send(200, node.page(int(since)))
                self._err(404, "not_found", f"no such endpoint: {u.path}")

            def do_POST(self):
                if urlparse(self.path).path == "/api/v1/measure":
                    return self._send(200, node.measure())
                self._err(404, "not_found", f"no such endpoint: {self.path}")

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{self.port}"

    # --- the firmware's state, simulated
    def _uptime(self) -> int:
        return int(time.monotonic() - self._t0)

    def measure(self) -> dict:
        with self._lock:
            steps = {"soil_moisture_pct": (0.6, 5, 95), "air_temp_c": (0.3, 2, 35),
                     "humidity_pct": (1.0, 25, 95), "light_lux": (400, 50, 40000)}
            for k, (step, lo, hi) in steps.items():
                self._v[k] = min(hi, max(lo, self._v[k] + self._rng.uniform(-1, 1) * step))
            self._seq += 1
            v = self._v
            r = {"v": 1, "device": self.device, "seq": self._seq,
                 "soil_moisture_pct": round(v["soil_moisture_pct"], 1), "air_temp_c": round(v["air_temp_c"], 1),
                 "humidity_pct": round(v["humidity_pct"]), "light_lux": round(v["light_lux"]),
                 "soil_raw": int(3200 - v["soil_moisture_pct"] / 100 * (3200 - 1350)), "uptime_s": self._uptime()}
            self._latest = r
            if time.monotonic() - self._last_log >= self.log_every_s:
                self._log.append(r)
                self._log = self._log[-360:]
                self._last_log = time.monotonic()
            return r

    def latest(self) -> dict:
        return self._latest or self.measure()

    def status(self) -> dict:
        return {"v": 1, "device": self.device, "firmware": "sim-1.0.0", "uptime_s": self._uptime(),
                "simulated": True, "clients": 1, "battery_pct": None, "battery_v": None,
                "latest_seq": self._latest["seq"] if self._latest else 0, "log_count": len(self._log),
                "log_every_s": int(self.log_every_s)}

    def page(self, since: int) -> dict:
        newer = [r for r in self._log if r["seq"] > since]
        return {"readings": newer[:PAGE_MAX], "latest_seq": self._latest["seq"] if self._latest else 0,
                "uptime_s": self._uptime(), "more": len(newer) > PAGE_MAX}

    # --- serving
    def start(self) -> SimulatedNode:
        self.measure()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
