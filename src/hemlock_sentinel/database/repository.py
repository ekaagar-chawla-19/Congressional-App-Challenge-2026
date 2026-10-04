"""SQLite repository: trees, observations, views, persistent ID allocation."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ..reid.multiview import l2_normalize
from .models import SCHEMA, ObservationRecord, TreeRecord, ViewRecord, from_blob, to_blob


class TreeRepository:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self._conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ IDs
    def _allocate_id(self, c: sqlite3.Connection, prefix: str, width: int = 3) -> str:
        row = c.execute("SELECT next_value FROM id_counters WHERE prefix=?", (prefix,)).fetchone()
        n = 1 if row is None else row["next_value"]
        c.execute("INSERT INTO id_counters(prefix, next_value) VALUES(?, ?) "
                  "ON CONFLICT(prefix) DO UPDATE SET next_value=excluded.next_value", (prefix, n + 1))
        return f"{prefix}-{n:0{width}d}"

    # ---------------------------------------------------------------- trees
    def create_tree(self, species: str, prefix: str, now: float | None = None) -> str:
        now = time.time() if now is None else now
        with self.tx() as c:
            tid = self._allocate_id(c, prefix)
            c.execute("INSERT INTO trees(tree_id, species, created_at, last_seen_at) VALUES(?,?,?,?)",
                      (tid, species, now, now))
        return tid

    def get_tree(self, tree_id: str) -> TreeRecord | None:
        r = self._conn.execute("SELECT * FROM trees WHERE tree_id=?", (tree_id,)).fetchone()
        return None if r is None else self._tree(r)

    def list_trees(self, species: str | None = None, include_merged: bool = False) -> list[TreeRecord]:
        q = "SELECT * FROM trees WHERE 1=1"
        args: list = []
        if species:
            q += " AND species=?"
            args.append(species)
        if not include_merged:
            q += " AND merged_into IS NULL"
        return [self._tree(r) for r in self._conn.execute(q + " ORDER BY created_at, tree_id", args)]

    @staticmethod
    def _tree(r) -> TreeRecord:
        return TreeRecord(r["tree_id"], r["species"], r["created_at"], r["last_seen_at"],
                          r["observation_count"], from_blob(r["canonical_embedding"]), r["merged_into"])

    # --------------------------------------------------------- observations
    def add_observation(self, obs: ObservationRecord) -> str:
        oid = obs.observation_id or uuid.uuid4().hex
        with self.tx() as c:
            c.execute(
                "INSERT INTO observations(observation_id, tree_id, timestamp, lat, lon, gps_accuracy_m, species,"
                " species_confidence, decision, match_probability, aggregated_embedding, model_version,"
                " environment_json, metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (oid, obs.tree_id, obs.timestamp, obs.lat, obs.lon, obs.gps_accuracy_m, obs.species,
                 obs.species_confidence, obs.decision, obs.match_probability, to_blob(obs.aggregated_embedding),
                 obs.model_version, json.dumps(obs.environment), json.dumps(obs.metadata)))
            for v in obs.views:
                c.execute(
                    "INSERT INTO views(observation_id, view_index, view_type, image_key, depth_key,"
                    " local_features_key, embedding, quality_json, heading_deg) VALUES(?,?,?,?,?,?,?,?,?)",
                    (oid, v.view_index, v.view_type, v.image_key, v.depth_key, v.local_features_key,
                     to_blob(v.embedding), json.dumps(v.quality), v.heading_deg))
            if obs.tree_id is not None:
                self._refresh_tree(c, obs.tree_id, obs.timestamp)
        return oid

    def _refresh_tree(self, c: sqlite3.Connection, tree_id: str, seen_at: float | None = None) -> None:
        rows = c.execute("SELECT aggregated_embedding, timestamp FROM observations WHERE tree_id=?"
                         " AND aggregated_embedding IS NOT NULL", (tree_id,)).fetchall()
        canon = None
        if rows:
            canon = l2_normalize(np.mean([l2_normalize(from_blob(r[0])) for r in rows], axis=0))
        last = max([r[1] for r in rows], default=seen_at or time.time())
        n = c.execute("SELECT COUNT(*) FROM observations WHERE tree_id=?", (tree_id,)).fetchone()[0]
        c.execute("UPDATE trees SET canonical_embedding=?, observation_count=?, last_seen_at=? WHERE tree_id=?",
                  (to_blob(canon), n, last, tree_id))

    def assign_observation(self, observation_id: str, tree_id: str, decision: str = "confirmed") -> None:
        """Attach an unresolved ('uncertain') observation to a tree after user confirmation."""
        with self.tx() as c:
            c.execute("UPDATE observations SET tree_id=?, decision=? WHERE observation_id=?",
                      (tree_id, decision, observation_id))
            self._refresh_tree(c, tree_id)

    def reassign_observation(self, observation_id: str, tree_id: str, decision: str = "user_corrected") -> None:
        """Move an observation to another tree (user correction). A tree left with no
        observations is retired as merged into the target; its ID is never reused."""
        with self.tx() as c:
            row = c.execute("SELECT tree_id FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
            if row is None:
                raise KeyError(observation_id)
            old = row[0]
            c.execute("UPDATE observations SET tree_id=?, decision=? WHERE observation_id=?",
                      (tree_id, decision, observation_id))
            self._refresh_tree(c, tree_id)
            if old is not None and old != tree_id:
                n = c.execute("SELECT COUNT(*) FROM observations WHERE tree_id=?", (old,)).fetchone()[0]
                if n == 0:
                    c.execute("UPDATE trees SET merged_into=?, observation_count=0, canonical_embedding=NULL"
                              " WHERE tree_id=?", (tree_id, old))
                else:
                    self._refresh_tree(c, old)

    def merge_trees(self, keep: str, drop: str) -> None:
        """Fix a duplicate: move drop's observations to keep. drop's ID is retired, not reused."""
        with self.tx() as c:
            c.execute("UPDATE observations SET tree_id=? WHERE tree_id=?", (keep, drop))
            c.execute("UPDATE trees SET merged_into=?, observation_count=0, canonical_embedding=NULL"
                      " WHERE tree_id=?", (keep, drop))
            self._refresh_tree(c, keep)

    def get_observations(self, tree_id: str, with_views: bool = True) -> list[ObservationRecord]:
        rows = self._conn.execute("SELECT * FROM observations WHERE tree_id=? ORDER BY timestamp", (tree_id,))
        return [self._obs(r, with_views) for r in rows.fetchall()]

    def get_observation(self, observation_id: str) -> ObservationRecord | None:
        r = self._conn.execute("SELECT * FROM observations WHERE observation_id=?", (observation_id,)).fetchone()
        return None if r is None else self._obs(r, True)

    def _obs(self, r, with_views: bool) -> ObservationRecord:
        o = ObservationRecord(
            r["observation_id"], r["tree_id"], r["timestamp"], r["decision"], r["species"],
            r["species_confidence"], r["match_probability"], from_blob(r["aggregated_embedding"]),
            r["lat"], r["lon"], r["gps_accuracy_m"], r["model_version"],
            json.loads(r["environment_json"] or "{}"), json.loads(r["metadata_json"] or "{}"))
        if with_views:
            for v in self._conn.execute("SELECT * FROM views WHERE observation_id=? ORDER BY view_index",
                                        (r["observation_id"],)):
                o.views.append(ViewRecord(v["view_index"], v["view_type"], v["image_key"], from_blob(v["embedding"]),
                                          json.loads(v["quality_json"] or "{}"), v["depth_key"],
                                          v["local_features_key"], v["heading_deg"]))
        return o

    def gallery(self, species: str) -> tuple[list[str], list[str], np.ndarray]:
        """(tree_ids, observation_ids, embeddings) of assigned observations of one species."""
        rows = self._conn.execute(
            "SELECT o.tree_id, o.observation_id, o.aggregated_embedding FROM observations o"
            " JOIN trees t ON t.tree_id = o.tree_id WHERE t.species=? AND t.merged_into IS NULL"
            " AND o.aggregated_embedding IS NOT NULL ORDER BY o.timestamp", (species,)).fetchall()
        if not rows:
            return [], [], np.zeros((0, 0), np.float32)
        return [r[0] for r in rows], [r[1] for r in rows], np.stack([from_blob(r[2]) for r in rows])

    def gallery_views(self, tree_id: str) -> list[ViewRecord]:
        rows = self._conn.execute(
            "SELECT v.* FROM views v JOIN observations o ON o.observation_id=v.observation_id"
            " WHERE o.tree_id=? ORDER BY o.timestamp, v.view_index", (tree_id,)).fetchall()
        return [ViewRecord(v["view_index"], v["view_type"], v["image_key"], from_blob(v["embedding"]),
                           json.loads(v["quality_json"] or "{}"), v["depth_key"], v["local_features_key"],
                           v["heading_deg"]) for v in rows]
