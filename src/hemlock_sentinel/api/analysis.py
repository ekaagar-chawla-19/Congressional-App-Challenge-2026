"""Tree, area and forest analysis from stored visits (photos, sensors, signs, findings)."""

from __future__ import annotations

import math
from collections import Counter

from ..database.repository import TreeRepository
from . import diseases, field, health

CONDITION_KEYS = tuple(diseases.CONDITIONS)


def tree_profiles(repo: TreeRepository) -> list[dict]:
    """Per active tree: location, latest severity, latest sensor reading, current status per condition
    (from the most recent visit that assessed it), visit counts."""
    status = {d["tree_id"]: d for d in health.tree_status(repo)}
    rows = repo.query("SELECT observation_id, tree_id, timestamp, decision FROM observations "
                      "WHERE tree_id IS NOT NULL ORDER BY timestamp")
    data = field.visit_data(repo, [r[0] for r in rows])
    imgs = {r[0] for r in repo.query("SELECT DISTINCT observation_id FROM views WHERE image_key IS NOT NULL")}
    prof: dict[str, dict] = {}
    for oid, tid, ts, _dec in rows:
        if tid not in status:
            continue
        p = prof.setdefault(tid, {**status[tid], "conditions": {}, "latest_sensors": None, "visits": 0,
                                  "visits_with_photos": 0, "visits_with_sensors": 0})
        p["visits"] += 1
        p["visits_with_photos"] += oid in imgs
        d = data[oid]
        if d["sensors"]:
            p["visits_with_sensors"] += 1
            p["latest_sensors"] = {**d["sensors"], "timestamp": ts}
        for f in d["findings"]:
            if f["level"] != "unknown":
                p["conditions"][f["condition"]] = {**f, "timestamp": ts}
    for tid, d in status.items():
        prof.setdefault(tid, {**d, "conditions": {}, "latest_sensors": None, "visits": 0,
                              "visits_with_photos": 0, "visits_with_sensors": 0})
    for p in prof.values():
        main = max(p["conditions"].values(), key=lambda f: f["likelihood"], default=None)
        p["main_condition"] = main["condition"] if main and main["likelihood"] >= 0.35 else None
    return list(prof.values())


def summarize(profiles: list[dict]) -> dict:
    """Aggregate a set of trees (a forest, a grid cell, or a selected area)."""
    n = len(profiles)
    sev = [p["severity"] for p in profiles if p["severity"] is not None]
    cond = {c: {"likely": 0, "possible": 0, "assessed": 0} for c in CONDITION_KEYS}
    for p in profiles:
        for c, f in p["conditions"].items():
            cond[c]["assessed"] += 1
            if f["level"] in ("likely", "possible"):
                cond[c][f["level"]] += 1
    sensors = {}
    for k in field.SENSOR_FIELDS:
        vals = [p["latest_sensors"][k] for p in profiles if p["latest_sensors"] and p["latest_sensors"].get(k) is not None]
        sensors[k] = {"mean": round(sum(vals) / len(vals), 1), "n": len(vals)} if vals else None
    counts = {c: v["likely"] + v["possible"] for c, v in cond.items()}
    prominent = max(counts, key=counts.get) if any(counts.values()) else None
    return {
        "trees": n,
        "severity_counts": health.severity_counts(profiles),
        "mean_severity": round(sum(sev) / len(sev), 2) if sev else None,
        "pct_moderate_or_severe": round(100 * sum(s >= 2 for s in sev) / len(sev), 1) if sev else None,
        "conditions": {c: {**v, "name": diseases.CONDITIONS[c]["name"]} for c, v in cond.items()},
        "most_prominent_condition": prominent,
        "sensor_means": sensors,
        "trees_with_sensor_data": sum(1 for p in profiles if p["latest_sensors"]),
        "trees_with_photos": sum(1 for p in profiles if p["visits_with_photos"]),
        "recommendations": diseases.recommendations(counts),
        "general_advice": diseases.GENERAL_ADVICE,
    }


def in_bbox(p: dict, bbox: tuple[float, float, float, float]) -> bool:
    w, s, e, n = bbox
    return p["lat"] is not None and s <= p["lat"] <= n and w <= p["lon"] <= e


def stress_score(p: dict) -> float:
    """0-1 ranking score for 'where are trees suffering most': severity plus likely/possible conditions."""
    sev = (p["severity"] or 0) / 3
    worst = max((f["likelihood"] for f in p["conditions"].values()), default=0.0)
    return round(0.6 * sev + 0.4 * worst, 3)


def zones(profiles: list[dict], cell_m: float = 150.0) -> list[dict]:
    """Square grid over the trees with locations; cells ranked worst first."""
    pts = [p for p in profiles if p["lat"] is not None]
    if not pts:
        return []
    lat0 = min(p["lat"] for p in pts)
    lon0 = min(p["lon"] for p in pts)
    dlat = cell_m / 111_320
    dlon = cell_m / (111_320 * math.cos(math.radians(lat0)))
    cells: dict[tuple[int, int], list[dict]] = {}
    for p in pts:
        cells.setdefault((int((p["lat"] - lat0) / dlat), int((p["lon"] - lon0) / dlon)), []).append(p)
    out = []
    for (i, j), ps in cells.items():
        s, w = lat0 + i * dlat, lon0 + j * dlon
        summ = summarize(ps)
        out.append({"zone_id": f"{i}-{j}", "bbox": [round(w, 6), round(s, 6), round(w + dlon, 6), round(s + dlat, 6)],
                    "center": {"lat": round(s + dlat / 2, 6), "lon": round(w + dlon / 2, 6)},
                    "stress_score": round(sum(stress_score(p) for p in ps) / len(ps), 3),
                    "tree_ids": sorted(p["tree_id"] for p in ps),
                    **{k: summ[k] for k in ("trees", "severity_counts", "mean_severity", "most_prominent_condition",
                                            "sensor_means")},
                    "condition_counts": {c: v["likely"] + v["possible"] for c, v in summ["conditions"].items()}})
    out.sort(key=lambda z: (-z["stress_score"], -z["trees"]))
    for rank, z in enumerate(out, 1):
        z["rank"] = rank
    return out


def condition_counter(profiles: list[dict]) -> Counter:
    return Counter(p["main_condition"] for p in profiles if p["main_condition"])
