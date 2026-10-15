"""Persistence schema (SQLite).

Design notes
* Tree IDs (``H-017``) are allocated from a per-prefix counter table inside a
  write transaction, never derived from row positions, and are never reused
  (deleting/merging a tree does not free its number).
* Images are stored once, content-addressed, by the Storage provider; the DB
  holds only the key. Original JPEG bytes are kept (no re-encode).
* Embeddings are float16 BLOBs: per-view (for view-consistency and future
  re-embedding comparisons) and per-observation aggregate (what retrieval
  searches). The tree's canonical embedding is derived (normalised mean of
  its observation embeddings) and cached on the tree row.
* Observations are timestamped and ordered per tree, which is all the future
  longitudinal / health-change work needs from this layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS id_counters (
    prefix TEXT PRIMARY KEY,
    next_value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS trees (
    tree_id TEXT PRIMARY KEY,
    species TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    observation_count INTEGER NOT NULL DEFAULT 0,
    canonical_embedding BLOB,
    merged_into TEXT REFERENCES trees(tree_id),
    notes TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    tree_id TEXT REFERENCES trees(tree_id),
    timestamp REAL NOT NULL,
    lat REAL, lon REAL, gps_accuracy_m REAL,
    species TEXT, species_confidence REAL,
    decision TEXT NOT NULL,
    match_probability REAL,
    aggregated_embedding BLOB,
    model_version TEXT,
    environment_json TEXT,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_tree_time ON observations(tree_id, timestamp);
CREATE TABLE IF NOT EXISTS views (
    view_id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    view_index INTEGER NOT NULL,
    view_type TEXT,
    image_key TEXT,
    depth_key TEXT,
    local_features_key TEXT,
    embedding BLOB,
    quality_json TEXT,
    heading_deg REAL
);
CREATE INDEX IF NOT EXISTS idx_views_obs ON views(observation_id);
"""


def to_blob(v: np.ndarray | None) -> bytes | None:
    if v is None:
        return None
    return np.asarray(v, dtype=np.float16).tobytes()


def from_blob(b: bytes | None) -> np.ndarray | None:
    if b is None:
        return None
    return np.frombuffer(b, dtype=np.float16).astype(np.float32)


@dataclass
class TreeRecord:
    tree_id: str
    species: str
    created_at: float
    last_seen_at: float
    observation_count: int
    canonical_embedding: np.ndarray | None = None
    merged_into: str | None = None
    notes: str | None = None


@dataclass
class ViewRecord:
    view_index: int
    view_type: str
    image_key: str | None
    embedding: np.ndarray | None
    quality: dict = field(default_factory=dict)
    depth_key: str | None = None
    local_features_key: str | None = None
    heading_deg: float | None = None


@dataclass
class ObservationRecord:
    observation_id: str
    tree_id: str | None
    timestamp: float
    decision: str
    species: str | None = None
    species_confidence: float | None = None
    match_probability: float | None = None
    aggregated_embedding: np.ndarray | None = None
    lat: float | None = None
    lon: float | None = None
    gps_accuracy_m: float | None = None
    model_version: str | None = None
    environment: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    views: list[ViewRecord] = field(default_factory=list)
