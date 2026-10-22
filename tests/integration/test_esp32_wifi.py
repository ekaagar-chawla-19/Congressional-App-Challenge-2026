"""The ESP32 Wi-Fi node (firmware/esp32_wifi_node) tested as far as possible without joining its network.

1. The firmware's reading JSON (reading_json.h) compiled on this computer and parsed by the backend.
2. The firmware and the simulated node serve the same routes.
3. The Python client and the CLI against the simulated node (paging, errors, unreachable node).
4. The phone app's own client (mobile/src/esp32.ts + device.ts) against the simulated node, under Node.

What this cannot test: the ESP32's access point and HTTP server themselves (checked by hand on a board:
see docs/esp32_wifi.md), radio range, and real sensors.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hemlock_sentinel.esp32 import bridge
from hemlock_sentinel.esp32.reading import parse_reading
from hemlock_sentinel.esp32.wifi import PAGE_MAX, NodeError, SimulatedNode, WifiNode

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "firmware" / "esp32_wifi_node"
STUBS = ROOT / "tests" / "firmware"
MOBILE = ROOT / "mobile"


@pytest.fixture
def node():
    with SimulatedNode(host="127.0.0.1", port=0, log_every_s=0, seed=1) as n:
        yield n


# ------------------------------------------------------------------ 1. firmware JSON
HARNESS = r"""
#include "arduino_stub.h"
#include "reading_json.h"
int g_adc = 0; float g_temp = 0, g_hum = 0, g_lux = 0; int g_dht_fail_reads = 0; unsigned long g_millis = 0;
int main() {
  Reading ok = {31.46f, 18.25f, 71.4f, 5400.4f, 2618, 7, 420};
  Reading dead = {NAN, NAN, NAN, NAN, -1, 8, 430};
  Reading partial = {12.0f, NAN, 55.0f, 0.0f, 2980, 9, 440};
  printf("ok\t%s\n", readingJson(ok, "HS-ESP32-1C49").c_str());
  printf("dead\t%s\n", readingJson(dead, "HS-ESP32-1C49").c_str());
  printf("partial\t%s\n", readingJson(partial, "HS-ESP32-1C49").c_str());
}
"""


@pytest.mark.skipif(shutil.which("g++") is None, reason="needs a C++ compiler")
def test_firmware_reading_json_parses(tmp_path):
    (tmp_path / "h.cpp").write_text(HARNESS)
    exe = tmp_path / "h"
    subprocess.run(["g++", "-std=c++17", "-I", str(STUBS), "-I", str(FIRMWARE), str(tmp_path / "h.cpp"), "-o", str(exe)],
                   check=True, capture_output=True)
    out = dict(l.split("\t", 1) for l in subprocess.run([str(exe)], check=True, capture_output=True,
                                                        text=True).stdout.strip().splitlines())
    raw = {k: json.loads(v) for k, v in out.items()}  # valid JSON, not just parseable by our parser
    r = {k: parse_reading(v) for k, v in out.items()}
    assert r["ok"]["device"] == "HS-ESP32-1C49" and raw["ok"]["seq"] == 7 and raw["ok"]["uptime_s"] == 420
    assert r["ok"]["sensors"] == {"soil_moisture_pct": 31.5, "air_temp_c": 18.2, "humidity_pct": 71.0, "light_lux": 5400.0}
    assert r["dead"]["sensors"] == dict.fromkeys(r["dead"]["sensors"])  # every failed sensor -> None (N/A)
    assert raw["dead"]["soil_raw"] is None
    assert r["partial"]["sensors"]["air_temp_c"] is None and r["partial"]["sensors"]["light_lux"] == 0.0


# ------------------------------------------------------------------ 2. same routes
def test_firmware_and_simulator_serve_the_same_routes():
    ino = (FIRMWARE / "esp32_wifi_node.ino").read_text()
    routes = set(re.findall(r'server\.on\("(/api/v1/[a-z]+)", HTTP_(GET|POST)', ino))
    assert routes == {("/api/v1/status", "GET"), ("/api/v1/reading", "GET"), ("/api/v1/measure", "POST"),
                      ("/api/v1/readings", "GET")}
    sim = (ROOT / "src/hemlock_sentinel/esp32/wifi.py").read_text()
    for path, _ in routes:
        assert f'"{path}"' in sim
    # status keys documented in the firmware header are the ones both build
    keys = re.search(r"GET  /api/v1/status\s+(\{.*?\})", ino, re.S).group(1)
    for k in re.findall(r'"(\w+)"', keys):
        assert f'\\"{k}\\"' in ino, k


# ------------------------------------------------------------------ 3. Python client + CLI
def test_client_reads_simulated_node(node):
    c = WifiNode(node.url)
    st = c.status()
    assert st["v"] == 1 and st["device"] == "HS-ESP32-SIM0" and st["simulated"] is True and st["battery_pct"] is None
    first, second = c.measure(), c.measure()
    assert second["raw"]["seq"] == first["raw"]["seq"] + 1
    assert set(first["sensors"]) == {"soil_moisture_pct", "air_temp_c", "humidity_pct", "light_lux"}
    assert all(v is not None for v in first["sensors"].values())
    assert c.reading()["raw"]["seq"] == second["raw"]["seq"]


def test_log_pages_and_since(node):
    for _ in range(PAGE_MAX + 25):
        node.measure()
    c = WifiNode(node.url)
    everything = c.readings(0)
    seqs = [r["raw"]["seq"] for r in everything]
    assert len(seqs) == PAGE_MAX + 26 and seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert [r["raw"]["seq"] for r in c.readings(seqs[-3])] == seqs[-2:]
    assert c.readings(seqs[-1]) == []


def test_errors(node):
    c = WifiNode(node.url)
    with pytest.raises(NodeError, match="HTTP 400.*whole number"):
        c._call("GET", "/api/v1/readings?since=abc")
    with pytest.raises(NodeError, match="HTTP 404"):
        c._call("GET", "/api/v1/nope")
    with pytest.raises(NodeError, match="cannot reach the sensor node"):
        WifiNode("http://127.0.0.1:9", timeout=1).status()


def test_cli_read_and_log(node, capsys):
    bridge.main(["read", "--wifi", node.url])
    assert capsys.readouterr().out.startswith("HS-ESP32-SIM0: soil_moisture_pct=")
    bridge.main(["log", "--wifi", node.url])
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) >= 2 and lines[0].startswith("#1 t+")
    with pytest.raises(SystemExit, match="cannot reach"):
        bridge.main(["read", "--wifi", "http://127.0.0.1:9"])


# ------------------------------------------------------------------ 4. the phone app's client
def _node_with_type_stripping() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return node if (int(v[0]), int(v[1])) >= (22, 6) else None


@pytest.mark.skipif(_node_with_type_stripping() is None, reason="needs Node 22.6+ (TypeScript type stripping)")
@pytest.mark.skipif(not (MOBILE / "node_modules" / "zustand").exists(), reason="run npm ci in mobile/")
def test_phone_app_client_against_simulated_node(node):
    res = subprocess.run([_node_with_type_stripping(), "--experimental-strip-types", "--no-warnings", "--import",
                          "./test/register-stubs.mjs", "test/esp32wifi.mjs", node.url],
                         cwd=MOBILE, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["unreachable_default"]["unreachable"] is True
    assert out["node_url"] == node.url and out["node_url_reset"] == "http://192.168.4.1"
    assert out["status"]["device"] == "HS-ESP32-SIM0"
    assert out["measure"]["device"] == "HS-ESP32-SIM0" and None not in out["measure"]["sensors"].values()
    assert [r["seq"] for r in out["log"]] == sorted(r["seq"] for r in out["log"]) and out["log"]
    assert all(0 <= r["age_s"] <= 30 for r in out["log"])
    assert out["discover"] == [{"id": "HS-ESP32-SIM0", "name": "HS-ESP32-SIM0", "signal": "Strong"}]
    assert out["connect"]["battery"] is None and out["connect"]["firmware"].endswith("simulated sensors")
    assert "not in range" in out["connect_wrong"]["error"]
    # a scan with the unit online carries a fresh reading; without a unit it is camera-only (no reading, no error)
    assert out["visit_reading"]["device"] == "HS-ESP32-SIM0" and None not in out["visit_reading"]["sensors"].values()
    assert out["visit_reading_no_unit"] is None and out["visit_reading_disconnected"] is None
    # only the sensors a reading has are shown; notes use the diagnosis thresholds
    assert out["present"] == ["soil_moisture_pct", "light_lux"]
    assert out["notes"] == ["bad", "warn", "warn"]  # dry soil, thirsty air (VPD), too dark


# ------------------------------------------------------------------ 5. backend: a reading can be taken back
def test_visit_reading_can_be_removed(tmp_path):
    """The app sends the unit's reading with the photos; "Don't save it" on the health check removes it again
    (DELETE /observations/{id}/sensors) and the visit's diagnosis is re-run without it."""
    import cv2
    from fastapi.testclient import TestClient

    from hemlock_sentinel.api.server import create_api
    from tests.helpers import tree_view
    from tests.integration.test_accounts_forests import make_accounts, signup

    c = TestClient(create_api(accounts=make_accounts(tmp_path)))
    h = signup(c, "unit@example.org")
    f = c.post("/api/v1/forests", json={"name": "Unit stand"}, headers=h).json()
    h = {**h, "X-Forest-Id": str(f["forest_id"])}
    jpeg = lambda v: cv2.imencode(".jpg", cv2.cvtColor(tree_view(30, v), cv2.COLOR_RGB2BGR))[1].tobytes()  # noqa: E731
    files = [("images", (f"{v}.jpg", jpeg(v), "image/jpeg")) for v in range(3)]
    dry = {"soil_moisture_pct": 9.0, "air_temp_c": 30.0, "humidity_pct": 30.0, "light_lux": 5000.0}
    r = c.post("/api/v1/identify", files=files, data={k: str(v) for k, v in dry.items()}, headers=h).json()
    oid = r["observation_id"]
    assert oid
    o = c.get(f"/api/v1/observations/{oid}", headers=h).json()
    assert o["sensors"] == dry
    assert any(x["condition"] == "drought_stress" and x["level"] in ("likely", "possible") for x in o["findings"])

    o = c.delete(f"/api/v1/observations/{oid}/sensors", headers=h)
    assert o.status_code == 200, o.text
    o = o.json()
    assert o["sensors"] is None
    assert all(x["condition"] != "drought_stress" or x["level"] == "unknown" for x in o["findings"])
    assert c.delete("/api/v1/observations/nope/sensors", headers=h).status_code == 404


def test_identify_stores_unless_commit_false(tmp_path):
    """An omitted `commit` form field means store (newer FastAPI reads an omitted bool form field as False, which
    made every one-shot identify a dry run: no tree ID, no visit). commit=false is still a dry run."""
    import cv2
    from fastapi.testclient import TestClient

    from hemlock_sentinel.api.server import create_api
    from tests.helpers import tree_view
    from tests.integration.test_accounts_forests import make_accounts, signup

    c = TestClient(create_api(accounts=make_accounts(tmp_path)))
    h = signup(c, "commit@example.org")
    f = c.post("/api/v1/forests", json={"name": "Commit stand"}, headers=h).json()
    h = {**h, "X-Forest-Id": str(f["forest_id"])}
    jpeg = lambda v: cv2.imencode(".jpg", cv2.cvtColor(tree_view(30, v), cv2.COLOR_RGB2BGR))[1].tobytes()  # noqa: E731
    files = lambda: [("images", (f"{v}.jpg", jpeg(v), "image/jpeg")) for v in range(3)]  # noqa: E731
    dry = c.post("/api/v1/identify", files=files(), data={"commit": "false"}, headers=h).json()
    assert dry["observation_id"] is None and dry["tree_id"] is None
    stored = c.post("/api/v1/identify", files=files(), headers=h).json()
    assert stored["tree_id"] == "H-001" and stored["observation_id"]
