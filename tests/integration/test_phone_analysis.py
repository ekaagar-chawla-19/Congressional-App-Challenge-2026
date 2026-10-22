"""The phone's forest analysis (mobile/src/analysis.ts, phone-only Insights) gives the backend's answers
(api/analysis.py + server.analysis_for / section_out).

Random forests (trees with and without locations, visits with signs, severity, sensors, several quarters) through
both, compared exactly: summary, hotspots, trends, sections and worst trees."""

import json
import math
import random
import subprocess

import pytest

from hemlock_sentinel.api import analysis as A
from hemlock_sentinel.api import diseases as D
from tests.integration.test_phone_diagnosis import MOBILE, SIGNS, _node, _sensors

KEYS = list(D.CONDITIONS)


def _forest(rng):
    lat0, lon0 = 34.7 + rng.random() / 10, -84.1 + rng.random() / 10
    trees, t0 = [], 1.69e12
    for i in range(rng.randint(1, 25)):
        located = rng.random() < 0.85
        t, visits = t0 + rng.uniform(0, 400) * 86_400_000, []
        for _ in range(rng.randint(1, 4)):
            t += rng.uniform(1, 200) * 86_400_000
            visits.append({"at": t, "severity": rng.choice([None, 0, 1, 2, 3]), "signs": rng.sample(SIGNS, rng.randint(0, 3)),
                           "sensors": _sensors(rng), "has_images": rng.random() < 0.8})
        trees.append({"id": f"H-{i:03d}", "lat": lat0 + rng.uniform(0, 0.006) if located else None,
                      "lon": lon0 + rng.uniform(0, 0.006) if located else None, "visits": visits})
    sections = [{"section_id": k + 1, "name": f"S{k}", "bbox": [lon0 + a, lat0 + b, lon0 + a + 0.003, lat0 + b + 0.003]}
                for k, (a, b) in enumerate([(0, 0), (0.002, 0.001), (0.004, 0.004)][: rng.randint(0, 3)])]
    bbox = None if rng.random() < 0.6 else [lon0 + 0.001, lat0 + 0.001, lon0 + 0.005, lat0 + 0.004]
    return {"trees": trees, "sections": sections, "bbox": bbox}


def _profiles(trees):
    """tree_profiles() from the same visits (it reads them from the database on the server)."""
    out = []
    for t in sorted((t for t in trees if t["visits"]), key=lambda t: t["visits"][0]["at"]):
        p = {"tree_id": t["id"], "lat": t["lat"], "lon": t["lon"], "severity": None, "conditions": {},
             "latest_sensors": None, "visits": 0, "visits_with_photos": 0}
        for v in t["visits"]:
            p["visits"] += 1
            p["visits_with_photos"] += v["has_images"]
            if v["severity"] is not None:
                p["severity"] = v["severity"]
            if v["sensors"]:
                p["latest_sensors"] = v["sensors"]
            for f in v["findings"]:
                if f["level"] != "unknown":
                    p["conditions"][f["condition"]] = {**f, "timestamp": v["at"]}
        main = max(p["conditions"].values(), key=lambda f: f["likelihood"], default=None)
        p["main_condition"] = main["condition"] if main and main["likelihood"] >= 0.35 else None
        out.append(p)
    return out


def _backend(c):
    for t in c["trees"]:
        for v in t["visits"]:
            v["findings"] = D.assess(v["signs"], v["sensors"], v["severity"], v["at"] / 1000, v["has_images"])
    all_p = _profiles(c["trees"])
    bbox = tuple(c["bbox"]) if c["bbox"] else None
    profs = [p for p in all_p if A.in_bbox(p, bbox)] if bbox else all_p
    ids = {p["tree_id"] for p in profs}
    rows = sorted(((t["id"], v["at"] / 1000, v["severity"], v["findings"]) for t in c["trees"] if t["id"] in ids
                   for v in t["visits"]), key=lambda r: r[1])
    summ = A.summarize(profs)
    del summ["trees_with_photos"]  # not shown by the app

    def section(sec):
        ps = [p for p in all_p if A.in_bbox(p, tuple(sec["bbox"]))]
        s = A.summarize(ps)
        return {"section_id": sec["section_id"], "name": sec["name"], "bbox": sec["bbox"], "trees": s["trees"],
                "mean_severity": s["mean_severity"], "pct_moderate_or_severe": s["pct_moderate_or_severe"],
                "most_prominent_condition": s["most_prominent_condition"],
                "stress_score": round(sum(A.stress_score(p) for p in ps) / len(ps), 3) if ps else None,
                "condition_counts": {k: v["likely"] + v["possible"] for k, v in s["conditions"].items()}}

    return {"area": dict(zip(("west", "south", "east", "north"), bbox, strict=True)) if bbox else None, "summary": summ,
            "hotspots": A.hotspots(profs), "trends": A.trends_from(rows),
            "sections": [] if bbox else [section(s) for s in c["sections"]],
            "worst_trees": [{"tree_id": p["tree_id"], "stress_score": A.stress_score(p), "severity": p["severity"],
                             "main_condition": p["main_condition"]} for p in sorted(profs, key=A.stress_score, reverse=True)[:10]]}


def _run(cases):
    res = subprocess.run([_node(), "--experimental-strip-types", "--no-warnings", "--import", "./test/register-stubs.mjs",
                          "test/analysis.mjs"], cwd=MOBILE, input="\n".join(json.dumps(c) for c in cases),
                         capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr
    return [json.loads(l) for l in res.stdout.strip().splitlines()]


@pytest.mark.skipif(_node() is None, reason="needs Node 22.6+")
def test_analysis_matches_backend():
    rng = random.Random(5)
    cases = [_forest(rng) for _ in range(300)]
    got = _run(json.loads(json.dumps(cases)))
    for c, g in zip(cases, got, strict=True):
        want = _backend(c)
        g.pop("round", None)
        assert g == want, (c["bbox"], {k: (g[k], want[k]) for k in want if g[k] != want[k]})


@pytest.mark.skipif(_node() is None, reason="needs Node 22.6+")
def test_python_rounding():
    rng = random.Random(3)
    vals = [(x, n) for x, n in [(0.125, 2), (0.375, 2), (2.5, 0), (3.5, 0), (-0.125, 2), (1.0005, 3), (0.0, 3)]]
    vals += [(rng.choice([rng.uniform(-100, 100), round(rng.uniform(0, 10), 3) + 0.0005]), rng.choice([1, 2, 3, 6]))
             for _ in range(3000)]
    vals += [(k / 8, n) for k in range(-40, 40) for n in (0, 1, 2)]
    got = _run([{"trees": [], "sections": [], "bbox": None, "round": vals}])[0]["round"]
    want = [round(x, n) for x, n in vals]
    bad = [(v, g, w) for v, g, w in zip(vals, got, want, strict=True) if not math.isclose(g, w, abs_tol=0) and g != w]
    assert not bad, bad[:10]


def test_condition_guide_is_the_servers():
    res = subprocess.run([_node(), "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e",
                          "const g = (await import('./src/conditionGuide.ts')).default; console.log(JSON.stringify(g))"],
                         cwd=MOBILE, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    g = json.loads(res.stdout)
    assert g["general_advice"] == D.GENERAL_ADVICE
    assert g["conditions"] == {c: {"name": v["name"], "recommendations": v["recommendations"], "confirm": v["confirm"]}
                               for c, v in D.CONDITIONS.items()}
    assert set(g["conditions"]) == set(KEYS)
