"""The ESP32 path tested as far as possible without the board.

1. The firmware's own measurement/JSON code (copied verbatim from esp32_sensors.ino) is compiled
   on this computer with stand-ins for the Arduino core and sensor libraries, run for many sensor
   situations, and its output is parsed by the Python parser and the app's TypeScript parser.
2. USB: a simulated node on a real pseudo-terminal, read with the real pyserial code path.
3. Bluetooth: the bridge against fake BLE stacks covering notify, fallback read, truncated
   notifications, refused notify, padding bytes and errors.

What this cannot test: radio range/pairing on real phones, the real DHT11/BH1750/probe readings,
ADC calibration, and the Arduino BLE library itself.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from hemlock_sentinel.esp32 import bridge
from hemlock_sentinel.esp32.reading import COMMAND_UUID, READING_UUID, BadReading, parse_reading

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "firmware" / "esp32_sensors" / "esp32_sensors.ino"
STUBS = ROOT / "tests" / "firmware"
CLIENT = ROOT / "client"


def firmware_outputs(tmp_path) -> dict[str, str]:
    src = FIRMWARE.read_text()
    defines = "\n".join(l for l in src.splitlines() if re.match(r"#define (PIN_SOIL|SOIL_RAW_)", l))
    body = src[src.index("String num("): src.index("class CommandCallbacks")]
    (tmp_path / "extracted.inc").write_text(defines + "\n" + body)
    exe = tmp_path / "harness"
    subprocess.run(["g++", "-std=c++17", "-I", str(STUBS), "-I", str(tmp_path), str(STUBS / "harness.cpp"),
                    "-o", str(exe)], check=True, capture_output=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    return dict(line.split("\t", 1) for line in out.strip().splitlines())


@pytest.mark.skipif(shutil.which("g++") is None, reason="needs a C++ compiler")
def test_firmware_output_parses_identically_in_python_and_the_app(tmp_path):
    out = firmware_outputs(tmp_path)
    py = {k: parse_reading(v) for k, v in out.items()}
    s = {k: r["sensors"] for k, r in py.items()}
    assert all(r["device"] == "HS-ESP32-1A2B" and r["raw"]["v"] == 1 for r in py.values())
    # soil % = 100 * (3200 - raw) / (3200 - 1350), clamped
    assert s["normal"] == {"soil_moisture_pct": 53.5, "air_temp_c": 21.0, "humidity_pct": 64.0, "light_lux": 5400.0}
    assert s["dry_soil"]["soil_moisture_pct"] == 10.8 and s["dry_soil"]["humidity_pct"] == 35.0
    assert s["wet_soil"]["soil_moisture_pct"] == 100.0
    for k in ("probe_disconnected_high", "probe_disconnected_low"):
        assert s[k]["soil_moisture_pct"] is None and s[k]["air_temp_c"] == 21.0  # only the probe is N/A
    assert s["dht_fails_once_then_ok"]["air_temp_c"] == 22.0  # the firmware's 2 s retry works
    assert s["dht_dead"]["air_temp_c"] is None and s["dht_dead"]["humidity_pct"] is None
    assert s["dht_dead"]["soil_moisture_pct"] is not None
    assert s["no_light_sensor"]["light_lux"] is None and s["light_sensor_error"]["light_lux"] is None
    assert s["freezing_edge"]["air_temp_c"] == 0.0
    for line in out.values():  # valid JSON with nulls, never "nan"
        assert "nan" not in line.lower() and json.loads(line)

    if shutil.which("node") and (CLIENT / "dist" / "esp32.js").exists():
        ts_in = "".join(f"{k}\t{v}\n" for k, v in out.items())
        res = subprocess.run(["node", "test/esp32.mjs"], cwd=CLIENT, input=ts_in, capture_output=True,
                             text=True, check=True).stdout
        ts = {k: json.loads(v) for k, v in (l.split("\t", 1) for l in res.strip().splitlines())}
        for k in out:
            assert ts[k]["sensors"] == s[k], k  # same N/A decisions, same numbers


def test_parser_rejects_and_tolerates():
    pad = b'{"v":1,"soil_moisture_pct":20,"air_temp_c":"bad","humidity_pct":"NaN"}\x00\x00\r\n'
    r = parse_reading(pad)
    assert r["sensors"] == {"soil_moisture_pct": 20.0, "air_temp_c": None, "humidity_pct": None, "light_lux": None}
    for bad in (b"", b"{", b'{"v":2}', b"[1,2]", b'"text"', b'{"event":"ready"}'):
        with pytest.raises(BadReading):
            parse_reading(bad)


# ------------------------------------------------------------------ USB: real pseudo-terminal
class FakeNodeOnTty(threading.Thread):
    """Behaves like the firmware on a serial line: boot banner, periodic readings, 'r' -> reading."""

    def __init__(self, fd, reply_to_r=True):
        super().__init__(daemon=True)
        self.fd, self.reply, self.stop = fd, reply_to_r, threading.Event()
        self.n = 0

    def line(self, soil):
        self.n += 1
        return (json.dumps({"v": 1, "device": "HS-ESP32-TTY0", "soil_moisture_pct": soil, "air_temp_c": 19.5,
                            "humidity_pct": 71, "light_lux": None, "soil_raw": 2400, "uptime_s": self.n})
                + "\r\n").encode()

    def run(self):
        os.write(self.fd, b'ets Jun  8 2016 boot garbage \xff\xfe\r\n{"event":"ready","device":"HS-ESP32-TTY0"}\r\n')
        while not self.stop.is_set():
            try:
                data = os.read(self.fd, 64)
            except OSError:
                return
            if self.reply and b"r" in data:
                time.sleep(0.2)  # measuring
                os.write(self.fd, self.line(33.3))


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs a pseudo-terminal")
def test_read_over_a_real_serial_port_with_pyserial():
    pytest.importorskip("serial")
    master, slave = os.openpty()
    node = FakeNodeOnTty(master)
    node.start()
    try:
        r = bridge.read_serial(os.ttyname(slave), timeout=5)
        assert r["device"] == "HS-ESP32-TTY0"
        assert r["sensors"] == {"soil_moisture_pct": 33.3, "air_temp_c": 19.5, "humidity_pct": 71.0, "light_lux": None}
    finally:
        node.stop.set()
        os.close(slave)
        os.close(master)


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs a pseudo-terminal")
def test_serial_times_out_cleanly_when_firmware_is_missing():
    pytest.importorskip("serial")
    master, slave = os.openpty()
    node = FakeNodeOnTty(master, reply_to_r=False)  # e.g. a different sketch is flashed
    node.start()
    try:
        t0 = time.monotonic()
        with pytest.raises(TimeoutError, match="firmware"):
            bridge.read_serial(os.ttyname(slave), timeout=1.5)
        assert time.monotonic() - t0 < 5
    finally:
        node.stop.set()
        os.close(slave)
        os.close(master)


# ------------------------------------------------------------------ Bluetooth LE: fake stacks
GOOD = b'{"v":1,"device":"HS-ESP32-1A2B","soil_moisture_pct":12.5,"air_temp_c":24,"humidity_pct":40,"light_lux":800}'
OLD = b'{"v":1,"device":"HS-ESP32-1A2B","soil_moisture_pct":40,"air_temp_c":20,"humidity_pct":70,"light_lux":900}'


def fake_ble(monkeypatch, *, notify="good", read=OLD, notify_delay=0.05, refuse_notify=False, connect_error=None):
    calls = []

    class Client:
        def __init__(self, address, timeout):
            calls.append(("connect", address))
            self.cb = None

        async def __aenter__(self):
            if connect_error:
                raise connect_error
            return self

        async def __aexit__(self, *a):
            calls.append(("disconnect",))

        async def start_notify(self, uuid, cb):
            if refuse_notify:
                raise RuntimeError("notify not permitted")
            calls.append(("notify", uuid))
            self.cb = cb

        async def stop_notify(self, uuid):
            calls.append(("stop_notify", uuid))

        async def write_gatt_char(self, uuid, data, response):
            calls.append(("write", uuid, data))
            if self.cb and notify:
                payload = {"good": GOOD + b"\x00", "truncated": GOOD[:20]}[notify]

                async def later():
                    await asyncio.sleep(notify_delay)
                    self.cb(None, bytearray(payload))

                asyncio.get_running_loop().create_task(later())

        async def read_gatt_char(self, uuid):
            calls.append(("read", uuid))
            return bytearray(read)

    async def discover(timeout, return_adv):
        return {"a": (NS(address="AA:BB", name="HS-ESP32-1A2B"), NS(local_name=None, service_uuids=[], rssi=-60))}

    monkeypatch.setattr(bridge, "_bleak", lambda: NS(BleakScanner=NS(discover=discover), BleakClient=Client))
    monkeypatch.setattr(bridge, "MEASURE_WAIT_S", 0.5)
    return calls


def test_ble_uses_the_fresh_notified_reading_not_the_stale_value(monkeypatch):
    calls = fake_ble(monkeypatch)
    r = asyncio.run(bridge.read_ble())
    assert r["sensors"]["soil_moisture_pct"] == 12.5  # fresh (the readable value is the old 40 %)
    assert ("notify", READING_UUID) in calls and ("write", COMMAND_UUID, b"r") in calls
    assert ("read", READING_UUID) not in calls and calls[-1] == ("disconnect",)
    assert ("stop_notify", READING_UUID) in calls


def test_ble_falls_back_to_reading_when_notify_is_truncated_late_or_refused(monkeypatch):
    for kw in ({"notify": "truncated"}, {"notify_delay": 2.0}, {"refuse_notify": True}, {"notify": None}):
        calls = fake_ble(monkeypatch, read=GOOD, **kw)
        r = asyncio.run(bridge.read_ble())
        assert r["sensors"]["soil_moisture_pct"] == 12.5, kw
        assert ("read", READING_UUID) in calls and calls[-1] == ("disconnect",), kw


def test_ble_errors_are_clear(monkeypatch):
    fake_ble(monkeypatch, connect_error=TimeoutError("connect timed out"))
    with pytest.raises(TimeoutError):
        asyncio.run(bridge.read_ble("AA:BB"))
    fake_ble(monkeypatch, notify=None, read=b"garbage")
    with pytest.raises(BadReading):
        asyncio.run(bridge.read_ble("AA:BB"))

    async def nothing(timeout, return_adv):
        return {}

    monkeypatch.setattr(bridge, "_bleak", lambda: NS(BleakScanner=NS(discover=nothing), BleakClient=None))
    with pytest.raises(TimeoutError, match="no Hemlock Sentinel ESP32"):
        asyncio.run(bridge.read_ble())
