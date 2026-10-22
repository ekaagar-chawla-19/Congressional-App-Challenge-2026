"""Phone-only mode's storage and diagnosis (mobile/src/data.ts) on a real SQLite database, under Node.

An old (v2) phone upgrades in place; a scan saved with its checklist, sensor reading and fingerprints is diagnosed on
the phone; a later reading on its own updates the diagnosis and the digital twin; a camera-only tree has no sensor
data anywhere; deleting a tree removes its readings and fingerprints."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MOBILE = Path(__file__).resolve().parents[2] / "mobile"


def _node():
    n = shutil.which("node")
    if not n:
        return None
    v = subprocess.run([n, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return n if (int(v[0]), int(v[1])) >= (22, 7) else None  # node:sqlite + TypeScript transform


@pytest.mark.skipif(_node() is None, reason="needs Node 22.7+")
@pytest.mark.skipif(not (MOBILE / "node_modules" / "zustand").exists(), reason="run npm ci in mobile/")
def test_phone_only_storage_and_diagnosis():
    res = subprocess.run([_node(), "--experimental-transform-types", "--no-warnings", "--import", "./test/register-stubs.mjs",
                          "test/phonedata.mjs"], cwd=MOBILE, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    o = json.loads(res.stdout)
    up = o["upgraded"]
    ins = o["insights"]
    assert ins["trees"] == o["demo"]["trees"] and ins["trends"] >= 1 and 1 <= ins["worst"] <= 10 and ins["recs"] >= 1
    assert ins["section_name"] == "Whole stand" and ins["section_trees"] == ins["located"] >= 1
    assert ins["listed"] == [["Whole stand", ins["located"]]] and "already exists" in ins["dup"] and ins["after_delete"] == 0
    assert up["version"] == 4 and up["trees"] == [["H-001", "watch", None]]
    # an old scan (graded signs only) gets its checklist back, so the tree keeps a diagnosis after the upgrade
    assert up["signs"] == ["twigs_checked_clean", "needle_loss"] and up["severity"] == 1
    assert ["hwa", "low"] in up["conditions"]
    assert o["demo"]["trees"] == 14 and o["demo"]["readings"] > 0 and 0 < o["demo"]["with_sensors"] <= 14

    sc = o["scan"]
    assert sc["signs"] == ["hwa_wool", "needle_loss"] and sc["severity"] == 2 and sc["fingerprints"] == 3
    assert sc["first"]["conditions"] == [["hwa", "likely"], ["drought_stress", "possible"]]
    assert sc["first"]["env"] == "High water stress: dry soil, thirsty air."
    assert sc["first"]["next"].startswith("Report the adelgid")
    # the moist reading two weeks later: drought now unlikely, HWA (seen on the twigs) still likely
    assert sc["after"]["conditions"] == [["hwa", "likely"], ["drought_stress", "low"]]
    assert sc["after"]["readings"] == 2 and sc["after"]["sensors"]["light_lux"] is None
    assert sc["after"]["env"]["summary"] == "Low water stress: moist soil, mild air."
    assert "Soil wetter by 29 points" in sc["after"]["env"]["changes"]
    assert any("less likely (60% → 5%)" in c for c in sc["after"]["changes"])
    # camera only (no unit): no sensor data anywhere
    assert sc["camera_only"] == {"sensors": None, "readings": 0, "conditions": []}
    assert [t["sensors"] for t in sc["listed"]][1] is None and sc["listed"][0]["conditions"]["hwa"] == 0.95
    assert o["deleted"] == {"readings": 0, "fingerprints": 0}
