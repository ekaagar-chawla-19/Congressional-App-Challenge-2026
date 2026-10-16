"""Minimal stdlib HTTP client for hemlock-api (used by the ESP32 bridge)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote


class ApiCallError(Exception):
    def __init__(self, error: dict):
        super().__init__(error.get("message"))
        self.error = error


class ApiClient:
    def __init__(self, base: str, email: str | None = None, password: str | None = None, timeout: float = 120):
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
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields.items() if v is not None]
        for i, p in enumerate(photos):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="images"; filename="p{i}.jpg"\r\n'
                         f"Content-Type: image/jpeg\r\n\r\n".encode() + p + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        return self._call("POST", "/identify", body, f"multipart/form-data; boundary={boundary}", forest_id)

    def visit(self, tree_id: str, payload: dict, forest_id: int | None) -> dict:
        return self._call("POST", f"/trees/{quote(tree_id)}/visits", json.dumps(payload).encode(),
                          "application/json", forest_id)
