"""The phone's diagnosis (mobile/src/diagnosis.ts) gives the backend's answers (api/diseases.py, api/twin.py).

Random visits (signs, severity, season, sensors incl. missing ones, AI scores) through both, compared exactly:
the phone-only mode must not diagnose differently from the server."""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from hemlock_sentinel.api import diseases as D
from hemlock_sentinel.api import twin as TW

MOBILE = Path(__file__).resolve().parents[2] / "mobile"
SIGNS = ["hwa_wool", "ehs_scale", "twigs_checked_clean", "needle_yellow_banding", "gray_green_foliage", "needle_loss",
         "no_new_growth", "branch_dieback", "drought_browning", "borer_holes", "root_rot_signs"]


def _node():
    n = shutil.which("node")
    if not n:
        return None
    v = subprocess.run([n, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return n if (int(v[0]), int(v[1])) >= (22, 6) else None


def _sensors(rng):
    if rng.random() < 0.15:
        return None
    pick = lambda lo, hi, nd: None if rng.random() < 0.2 else round(rng.uniform(lo, hi), nd)  # noqa: E731
    return {"soil_moisture_pct": pick(0, 60, 1), "air_temp_c": pick(-25, 40, 1), "humidity_pct": pick(10, 100, 0),
            "light_lux": pick(0, 30000, 0)}


def _case(rng):
    when = rng.choice([None, rng.uniform(1.6e12, 1.8e12)])
    ai = None if rng.random() < 0.7 else {k: round(rng.random(), 2) for k in ("hwa_wool", "ehs_scale", "needle_yellow_banding")
                                          if rng.random() < 0.7}
    return {"kind": "assess", "signs": rng.sample(SIGNS, rng.randint(0, 4)), "sensors": _sensors(rng),
            "severity": rng.choice([None, 0, 1, 2, 3]), "when": when, "has_images": rng.random() < 0.5, "ai": ai}


def _run(cases):
    res = subprocess.run([_node(), "--experimental-strip-types", "--no-warnings", "--import", "./test/register-stubs.mjs",
                          "test/diagnosis.mjs"], cwd=MOBILE, input="\n".join(json.dumps(c) for c in cases),
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    return [json.loads(l) for l in res.stdout.strip().splitlines()]


@pytest.mark.skipif(_node() is None, reason="needs Node 22.6+")
def test_assess_matches_backend():
    rng = random.Random(7)
    cases = [_case(rng) for _ in range(3000)]
    for c, got in zip(cases, _run(cases), strict=True):
        want = D.assess(c["signs"], c["sensors"], c["severity"], c["when"] / 1000 if c["when"] else None,
                        c["has_images"], c["ai"])
        assert [{k: f[k] for k in ("condition", "likelihood", "level", "evidence")} for f in got] == want, c


@pytest.mark.skipif(_node() is None, reason="needs Node 22.6+")
def test_twin_matches_backend():
    rng = random.Random(11)
    cases = []
    for _ in range(600):
        t, visits = 1.7e12, []
        for i in range(rng.randint(1, 5)):
            t += rng.uniform(1, 90) * 86_400_000
            visits.append({"id": f"o{i}", "at": t, "severity": rng.choice([None, 0, 1, 2, 3]),
                           "signs": rng.sample(SIGNS, rng.randint(0, 3)), "sensors": _sensors(rng)})
        cases.append({"kind": "twin", "visits": visits})
    for c, got in zip(cases, _run(cases), strict=True):
        obs = []
        for v in c["visits"]:
            s = v["sensors"] if v["sensors"] and any(x is not None for x in v["sensors"].values()) else None
            obs.append({"observation_id": v["id"], "timestamp": v["at"], "severity": v["severity"], "signs": v["signs"],
                        "sensors": s, "findings": D.assess(v["signs"], s, v["severity"], v["at"] / 1000)})
        hist = TW.sensor_history(obs)
        env = TW.environment(hist)
        cur = {}
        for o in obs:
            for f in o["findings"]:
                if f["level"] != "unknown":
                    cur[f["condition"]] = f
        cur = sorted(cur.values(), key=lambda f: -f["likelihood"])
        assert got["env"] == env, c
        assert got["since"] == TW.since_last_visit(obs), c
        assert got["next"] == TW.next_action(obs, cur, env), c
        assert got["current"] == [f["condition"] for f in cur], c
