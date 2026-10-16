"""Tree health (severity) recorded by the observer, and the forest map built from it.

The model does NOT estimate severity: it identifies species and individual trees.
Severity is the field rating the person enters at capture time (e.g. hemlock woolly
adelgid infestation), stored per observation; a tree's current severity is its most
recent rating. A health model could fill the same field later.
"""

from __future__ import annotations

import time

from ..database.repository import TreeRepository

SEVERITY = {0: "none", 1: "light", 2: "moderate", 3: "severe"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tree_health (
    observation_id TEXT PRIMARY KEY REFERENCES observations(observation_id),
    severity INTEGER CHECK (severity BETWEEN 0 AND 3),
    notes TEXT,
    recorded_at REAL NOT NULL
);
"""


def ensure_schema(repo: TreeRepository) -> None:
    with repo.tx() as c:
        c.execute(SCHEMA)


def set_health(repo: TreeRepository, observation_id: str, severity: int | None, notes: str | None) -> None:
    with repo.tx() as c:
        c.execute("INSERT INTO tree_health(observation_id, severity, notes, recorded_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(observation_id) DO UPDATE SET severity=excluded.severity, notes=excluded.notes, "
                  "recorded_at=excluded.recorded_at", (observation_id, severity, notes, time.time()))


def health_for(repo: TreeRepository, observation_ids: list[str]) -> dict[str, tuple[int | None, str | None]]:
    if not observation_ids:
        return {}
    rows = repo.query(f"SELECT observation_id, severity, notes FROM tree_health WHERE observation_id IN "
                      f"({','.join('?' * len(observation_ids))})", observation_ids)
    return {r[0]: (r[1], r[2]) for r in rows}


def tree_status(repo: TreeRepository) -> list[dict]:
    """Per active tree: latest location, latest severity rating, counts. One row per tree."""
    trees = {t.tree_id: t for t in repo.list_trees()}
    rows = repo.query(
        "SELECT o.tree_id, o.timestamp, o.lat, o.lon, h.severity, h.notes FROM observations o "
        "LEFT JOIN tree_health h ON h.observation_id = o.observation_id "
        "WHERE o.tree_id IS NOT NULL ORDER BY o.timestamp")
    out: dict[str, dict] = {}
    for tid, ts, lat, lon, sev, notes in rows:
        if tid not in trees:
            continue
        d = out.setdefault(tid, {"tree_id": tid, "lat": None, "lon": None, "severity": None, "health_notes": None,
                                 "severity_history": []})
        if lat is not None:
            d["lat"], d["lon"] = lat, lon
        if sev is not None:
            d["severity"], d["health_notes"] = sev, notes
            d["severity_history"].append({"timestamp": ts, "severity": sev})
    for tid, d in out.items():
        t = trees[tid]
        d.update(species=t.species, observation_count=t.observation_count, last_seen_at=t.last_seen_at,
                 created_at=t.created_at, notes=t.notes)
    return list(out.values())


def severity_counts(status: list[dict]) -> dict[str, int]:
    counts = {name: 0 for name in SEVERITY.values()} | {"unrated": 0}
    for d in status:
        counts[SEVERITY.get(d["severity"], "unrated")] += 1
    return counts
