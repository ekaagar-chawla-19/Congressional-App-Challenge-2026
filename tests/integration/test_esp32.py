"""ESP32 sensor node: reading format, USB/BLE reading (fake transports), firmware Wi-Fi upload
payload, and the hemlock-esp32 command against a live backend."""

import asyncio
import socket
import threading
import time
from types import SimpleNamespace as NS

import cv2
import pytest
import uvicorn
from fastapi.testclient import TestClient

from hemlock_sentinel.api.server import create_api
from hemlock_sentinel.esp32 import bridge
from hemlock_sentinel.esp32.reading import COMMAND_UUID, READING_UUID, SERVICE_UUID, BadReading, parse_reading
from tests.helpers import tree_view
from tests.integration.test_accounts_forests import make_accounts, signup

# exactly what firmware/esp32_sensors prints / serves (DHT11 failed -> null)
FIRMWARE_JSON = ('{"v":1,"device":"HS-ESP32-1A2B","soil_moisture_pct":11.5,"air_temp_c":null,'
                 '"humidity_pct":null,"light_lux":5400,"soil_raw":2950,"uptime_s":42}')


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def test_parse_reading():
    r = parse_reading(FIRMWARE_JSON.encode())
    assert r["device"] == "HS-ESP32-1A2B"
    assert r["sensors"] == {"soil_moisture_pct": 11.5, "air_temp_c": None, "humidity_pct": None, "light_lux": 5400.0}
    assert parse_reading('{"v":1,"soil_moisture_pct":140}')["sensors"]["soil_moisture_pct"] is None
    for bad in (b"{\"event\":\"ready\"}", b"upload -> HTTP 201", b"\xff\xfe"):
        with pytest.raises(BadReading):
            parse_reading(bad)


def test_read_over_usb_serial():
    class FakePort:
        def __init__(self):
            self.lines = [b'{"event":"ready","device":"HS-ESP32-1A2B"}\r\n', b"", FIRMWARE_JSON.encode() + b"\r\n"]
            self.written = b""

        def write(self, b):
            self.written += b

        def readline(self):
            return self.lines.pop(0) if self.lines else b""

    port = FakePort()
    assert bridge.read_serial_stream(port)["sensors"]["light_lux"] == 5400.0
    assert port.written == b"r\n"
    with pytest.raises(TimeoutError):
        bridge.read_serial_stream(NS(write=lambda b: None, readline=lambda: b""), 0.2)


def test_read_over_ble_with_fake_stack(monkeypatch):
    calls = []

    class Client:
        def __init__(self, address, timeout):
            calls.append(("connect", address))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            calls.append(("disconnect",))

        async def write_gatt_char(self, uuid, data, response):
            calls.append(("write", uuid, data))

        async def read_gatt_char(self, uuid):
            calls.append(("read", uuid))
            return bytearray(FIRMWARE_JSON.encode())

    async def discover(timeout, return_adv):
        return {"a": (NS(address="AA:BB", name="HS-ESP32-1A2B"), NS(local_name=None, service_uuids=[], rssi=-60)),
                "b": (NS(address="CC:DD", name="headphones"), NS(local_name=None, service_uuids=[], rssi=-30)),
                "c": (NS(address="EE:FF", name=None), NS(local_name=None, service_uuids=[SERVICE_UUID], rssi=-80))}

    monkeypatch.setattr(bridge, "_bleak", lambda: NS(BleakScanner=NS(discover=discover), BleakClient=Client))
    monkeypatch.setattr(bridge, "MEASURE_WAIT_S", 0)
    assert [a for a, _, _ in asyncio.run(bridge.scan())] == ["AA:BB", "EE:FF"]  # ours only, nearest first
    r = asyncio.run(bridge.read_ble())
    assert r["sensors"]["soil_moisture_pct"] == 11.5
    assert calls == [("connect", "AA:BB"), ("write", COMMAND_UUID, b"r"), ("read", READING_UUID), ("disconnect",)]


def test_firmware_wifi_upload_payload_is_accepted(tmp_path):
    c = TestClient(create_api(accounts=make_accounts(tmp_path)))
    h = signup(c, "node@example.org")
    f = c.post("/api/v1/forests", json={"name": "Node stand"}, headers=h).json()
    h = {**h, "X-Forest-Id": str(f["forest_id"])}
    files = [("images", (f"{v}.jpg", _jpeg(tree_view(30, v)), "image/jpeg")) for v in range(3)]
    assert c.post("/api/v1/identify", files=files, headers=h).json()["tree_id"] == "H-001"
    # firmware uploadVisit(): {"sensors": <reading JSON>}, extra keys and nulls included
    r = c.post("/api/v1/trees/H-001/visits", content='{"sensors":' + FIRMWARE_JSON + "}",
               headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["has_photos"] is False and o["sensors"] == {"soil_moisture_pct": 11.5, "air_temp_c": None,
                                                         "humidity_pct": None, "light_lux": 5400.0}
    assert any(f["condition"] == "drought_stress" and f["level"] != "unknown" for f in o["findings"])


@pytest.fixture
def live(tmp_path):
    acc = make_accounts(tmp_path)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_api(accounts=acc), log_level="warning"))
    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}", acc
    server.should_exit = True
    t.join(5)


def test_cli_identify_and_visit(live, tmp_path, monkeypatch, capsys):
    url, acc = live
    u = acc.register("lap@example.org", "laptop-password", "Laptop")
    forest = acc.create_forest(u.user_id, "Cove")
    monkeypatch.setattr(bridge, "read_node", lambda args: parse_reading(FIRMWARE_JSON))
    photos = []
    for v in range(3):
        p = tmp_path / f"{v}.jpg"
        p.write_bytes(_jpeg(tree_view(40, v)))
        photos.append(str(p))
    common = ["--api", url, "--email", "lap@example.org", "--password", "laptop-password",
              "--forest", str(forest.forest_id)]
    bridge.main(["identify", *photos, *common, "--lat", "34.8", "--lon", "-84.1", "--signs", "hwa_wool"])
    out = capsys.readouterr().out
    assert "soil_moisture_pct=11.5%" in out and "air_temp_c=N/A" in out and "new: H-001" in out
    assert "Hemlock woolly adelgid (HWA): likely" in out
    bridge.main(["visit", "H-001", *common, "--severity", "1"])
    assert "visit stored for H-001" in capsys.readouterr().out
    repo = acc.pipeline(forest).repo
    obs = repo.get_observations("H-001")
    from hemlock_sentinel.api import field
    data = field.visit_data(repo, [o.observation_id for o in obs])
    assert [data[o.observation_id]["sensors"]["soil_moisture_pct"] for o in obs] == [11.5, 11.5]
    assert data[obs[0].observation_id]["sensors"]["source"] == "esp32"
    with pytest.raises(SystemExit):
        bridge.main(["visit", "H-404", *common])
    assert "tree_not_found" in capsys.readouterr().err
