"""Dataset manifests and leakage-safe splits.

Rules enforced here (and tested in tests/unit/test_splits.py):

1. Identity-disjoint: a physical tree is in exactly one of train / val / test
   for re-identification. Re-ID test trees are never seen in training.
2. Capture-grouped: images that come from the same capture event (same tree,
   date and time in BarkNet file names) are never split across gallery and
   query, so "new view" queries are not near-duplicates of gallery images.
3. Open-set: only a fraction of test trees are enrolled in the gallery; the
   rest are "new tree" queries that must be rejected.

Every report produced from these splits states which regime it is and
whether test identities occurred in training.
"""

from __future__ import annotations

import csv
import random
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

BARKNET_RE = re.compile(r"^(\d+)_([A-Z]+)_(\d+)_(.+)_(\d{8})_(\d{6})_(\d+)$")


@dataclass
class ImageRecord:
    path: str
    tree_id: str  # globally unique physical tree, e.g. "PRU-402"
    species: str
    session: str  # capture date, yyyymmdd
    capture: str  # capture event id (tree + date + time)
    device: str
    circumference_cm: float
    view_index: int


def parse_barknet(root: str | Path, species_map: dict[str, str]) -> list[ImageRecord]:
    recs = []
    for p in sorted(Path(root).rglob("*.jpg")):
        m = BARKNET_RE.match(p.stem)
        if not m:
            continue
        num, code, circ, device, date, time, crop = m.groups()
        if code not in species_map:
            continue
        tid = f"{code}-{num}"
        recs.append(ImageRecord(str(p), tid, species_map[code], date, f"{tid}@{date}T{time}",
                                device, float(circ), int(crop)))
    return recs


def write_manifest(recs: list[ImageRecord], path: str | Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(recs[0]).keys()))
        w.writeheader()
        for r in recs:
            w.writerow(asdict(r))


def read_manifest(path: str | Path) -> list[ImageRecord]:
    with open(path) as f:
        return [ImageRecord(**{**row, "circumference_cm": float(row["circumference_cm"]),
                               "view_index": int(row["view_index"])}) for row in csv.DictReader(f)]


def split_identities(tree_ids: list[str], fractions: tuple[float, float, float], seed: int) -> tuple[list[str], list[str], list[str]]:
    ids = sorted(set(tree_ids))
    random.Random(seed).shuffle(ids)
    n = len(ids)
    n_train = int(round(fractions[0] * n))
    n_val = int(round(fractions[1] * n))
    return ids[:n_train], ids[n_train:n_train + n_val], ids[n_train + n_val:]


@dataclass
class Observation:
    """A simulated multi-view capture: several images of one tree from one capture group."""

    obs_id: str
    tree_id: str
    paths: list[str]
    session: str


def make_observations(recs: list[ImageRecord], views_per_obs: int, seed: int) -> list[Observation]:
    """Group each tree's images into disjoint observations of ``views_per_obs`` images.

    Images from one capture event stay in the same observation group when the
    tree has more than one capture (so a query never shares a capture with the
    gallery); trees with a single capture are partitioned into disjoint image
    sets, which is the BarkNet "same session, new bark region" regime.
    """
    rng = random.Random(seed)
    by_tree: dict[str, dict[str, list[ImageRecord]]] = defaultdict(lambda: defaultdict(list))
    for r in recs:
        by_tree[r.tree_id][r.capture].append(r)
    obs = []
    for tid in sorted(by_tree):
        caps = by_tree[tid]
        for cap in sorted(caps):
            imgs = sorted(caps[cap], key=lambda r: r.path)
            rng.shuffle(imgs)
            for k in range(len(imgs) // views_per_obs):
                chunk = imgs[k * views_per_obs:(k + 1) * views_per_obs]
                obs.append(Observation(f"{cap}#{k}", tid, [r.path for r in chunk], chunk[0].session))
    return obs


def gallery_query_split(obs: list[Observation], enrolled_fraction: float, seed: int):
    """Open-set protocol over test trees.

    Enrolled trees: first observation -> gallery, remaining -> known queries.
    Non-enrolled trees: all observations -> "new tree" queries (gallery has
    none of their images). When a tree has several capture events, gallery and
    query observations come from different capture events where possible.
    """
    rng = random.Random(seed)
    trees = sorted({o.tree_id for o in obs})
    rng.shuffle(trees)
    n_enr = int(round(enrolled_fraction * len(trees)))
    enrolled = set(trees[:n_enr])
    by_tree = defaultdict(list)
    for o in obs:
        by_tree[o.tree_id].append(o)
    gallery, known_q, new_q = [], [], []
    for t in sorted(by_tree):
        os_ = sorted(by_tree[t], key=lambda o: o.obs_id)
        if t in enrolled and len(os_) >= 2:
            g = os_[0]
            gallery.append(g)
            g_cap = g.obs_id.split("#")[0]
            others = [o for o in os_[1:]]
            # prefer queries from a different capture event than the gallery
            diff_cap = [o for o in others if o.obs_id.split("#")[0] != g_cap]
            known_q.extend(diff_cap or others)
        elif t in enrolled:
            gallery.append(os_[0])
        else:
            new_q.extend(os_)
    return gallery, known_q, new_q
