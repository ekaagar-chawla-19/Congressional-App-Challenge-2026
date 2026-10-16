"""Per-visit field data stored next to a forest's tree database.

A visit (= one observation row) can have photos, Raspberry Pi sensor readings,
observer-checked signs, or any combination. Missing parts are simply absent and
the API reports them as null ("N/A" in the app).

* visit_sensors : soil moisture (%), air temperature (deg C), relative humidity (%), light (lux)
* visit_signs   : signs the observer ticked (keys from diseases.SIGNS)
* visit_findings: per-condition assessment computed by diseases.assess() (refreshed on every change)
"""

from __future__ import annotations

import json
import time

from ..database.repository import TreeRepository

SENSOR_FIELDS = ("soil_moisture_pct", "air_temp_c", "humidity_pct", "light_lux")
SENSOR_RANGES = {"soil_moisture_pct": (0, 100), "air_temp_c": (-40, 60), "humidity_pct": (0, 100),
                 "light_lux": (0, 200_000)}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS visit_sensors (
        observation_id TEXT PRIMARY KEY REFERENCES observations(observation_id),
        soil_moisture_pct REAL, air_temp_c REAL, humidity_pct REAL, light_lux REAL,
        source TEXT, recorded_at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS visit_signs (
        observation_id TEXT PRIMARY KEY REFERENCES observations(observation_id),
        signs_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS visit_findings (
        observation_id TEXT NOT NULL REFERENCES observations(observation_id),
        condition TEXT NOT NULL, likelihood REAL NOT NULL, level TEXT NOT NULL,
        evidence_json TEXT NOT NULL, PRIMARY KEY (observation_id, condition))""",
    """CREATE TABLE IF NOT EXISTS visit_ai_inspection (
        observation_id TEXT PRIMARY KEY REFERENCES observations(observation_id),
        result_json TEXT NOT NULL, inspected_at REAL NOT NULL)""",
]


def ensure_schema(repo: TreeRepository) -> None:
    with repo.tx() as c:
        for s in SCHEMA:
            c.execute(s)


def clean_sensors(d: dict | None) -> dict | None:
    """Keep known fields; reject out-of-range values. None if nothing left."""
    if not d:
        return None
    out = {}
    for k in SENSOR_FIELDS:
        v = d.get(k)
        if v is None or v == "":
            continue
        v = float(v)
        lo, hi = SENSOR_RANGES[k]
        if not lo <= v <= hi:
            raise ValueError(f"{k}={v} outside {lo}..{hi}")
        out[k] = v
    return out or None


def set_sensors(repo: TreeRepository, oid: str, sensors: dict, source: str = "rpi") -> None:
    with repo.tx() as c:
        c.execute("INSERT OR REPLACE INTO visit_sensors(observation_id, soil_moisture_pct, air_temp_c, humidity_pct,"
                  " light_lux, source, recorded_at) VALUES(?,?,?,?,?,?,?)",
                  (oid, *[sensors.get(k) for k in SENSOR_FIELDS], source, time.time()))


def set_signs(repo: TreeRepository, oid: str, signs: list[str]) -> None:
    with repo.tx() as c:
        c.execute("INSERT OR REPLACE INTO visit_signs(observation_id, signs_json) VALUES(?,?)",
                  (oid, json.dumps(sorted(set(signs)))))


def set_findings(repo: TreeRepository, oid: str, findings: list[dict]) -> None:
    with repo.tx() as c:
        c.execute("DELETE FROM visit_findings WHERE observation_id=?", (oid,))
        for f in findings:
            c.execute("INSERT INTO visit_findings(observation_id, condition, likelihood, level, evidence_json) "
                      "VALUES(?,?,?,?,?)", (oid, f["condition"], f["likelihood"], f["level"], json.dumps(f["evidence"])))


def set_ai_inspection(repo: TreeRepository, oid: str, result: dict) -> None:
    with repo.tx() as c:
        c.execute("INSERT OR REPLACE INTO visit_ai_inspection(observation_id, result_json, inspected_at) "
                  "VALUES(?,?,?)", (oid, json.dumps(result), time.time()))


def ai_signs(inspection: dict | None) -> dict[str, float]:
    """AI-suggested signs (key -> confidence) from a usable inspection."""
    if not inspection or not inspection.get("usable"):
        return {}
    return {s["key"]: float(s["confidence"]) for s in inspection.get("signs", [])}


def _in(oids: list[str]) -> str:
    return ",".join("?" * len(oids))


def visit_data(repo: TreeRepository, oids: list[str]) -> dict[str, dict]:
    """observation_id -> {"sensors": dict|None, "signs": list, "findings": list, "ai_inspection": dict|None}"""
    out = {o: {"sensors": None, "signs": [], "findings": [], "ai_inspection": None} for o in oids}
    if not oids:
        return out
    for r in repo.query(f"SELECT * FROM visit_sensors WHERE observation_id IN ({_in(oids)})", oids):
        out[r["observation_id"]]["sensors"] = {k: r[k] for k in SENSOR_FIELDS} | {"source": r["source"]}
    for r in repo.query(f"SELECT * FROM visit_signs WHERE observation_id IN ({_in(oids)})", oids):
        out[r["observation_id"]]["signs"] = json.loads(r["signs_json"])
    for r in repo.query(f"SELECT * FROM visit_ai_inspection WHERE observation_id IN ({_in(oids)})", oids):
        out[r["observation_id"]]["ai_inspection"] = json.loads(r["result_json"])
    for r in repo.query(f"SELECT * FROM visit_findings WHERE observation_id IN ({_in(oids)}) "
                        "ORDER BY likelihood DESC", oids):
        out[r["observation_id"]]["findings"].append(
            {"condition": r["condition"], "likelihood": r["likelihood"], "level": r["level"],
             "evidence": json.loads(r["evidence_json"])})
    return out
