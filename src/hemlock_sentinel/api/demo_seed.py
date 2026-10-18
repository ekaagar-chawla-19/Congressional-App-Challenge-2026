"""Demo account with North Georgia forests of PLACEHOLDER hemlocks.

The placeholder trees have plausible positions, visit dates, severity ratings, signs and
sensor readings so the account overview, map, sections and trends can be shown, but they
have no photos and their embeddings are random (they never match a real capture).
Everything is tagged ``demo_seed`` and the account is clearly named. Real captures made
while signed in as the demo user are stored and matched normally.

The Chattahoochee forest follows the streams in geography.py and has a different pattern
per condition, so the disease hotspots differ:
* HWA spreading upstream from the west (lower Cooper Creek and Bryant Creek worst),
* elongate hemlock scale concentrated on Mulky Creek,
* drought stress on Shanty Branch (drier, sunnier slope).

seed_demo() is idempotent and also upgrades an older demo account (adds missing forests,
removes the earlier stand-in "Cooper Creek" forest if it holds only demo data).
"""

from __future__ import annotations

import math
import random
import time
import uuid

import numpy as np

from ..database.models import ObservationRecord
from . import diseases, field, geography, health, sections
from .accounts import Accounts, User

DEMO_EMAIL = "demo@hemlock.test"
DEMO_PASSWORD = "hemlock-demo"
CHATTAHOOCHEE = "Cooper Creek Scenic Area, Chattahoochee NF (demo)"
CHATTAHOOCHEE_TREES = 64
STREAM_FORESTS = [  # name, centre (approx.), number of placeholder trees, stream bearing (deg)
    ("Cloudland Canyon State Park (demo)", 34.8335, -85.4816, 28, 35.0),
]
LEGACY = ["Cooper Creek, Chattahoochee NF (demo)"]
DAY = 86400.0
SPECIES = "tsuga_canadensis"


def seed_demo(accounts: Accounts, now: float | None = None, seed: int = 7) -> User:
    user = accounts.find_user(DEMO_EMAIL) or accounts.register(DEMO_EMAIL, DEMO_PASSWORD, "Demo Field Team")
    now = time.time() if now is None else now
    have = {f.name: f for f in accounts.forests(user.user_id)}
    for name in LEGACY:
        f = have.get(name)
        if f is not None and _only_demo_data(accounts, f):
            accounts.delete_forest(user.user_id, f.forest_id)
    if CHATTAHOOCHEE not in have:
        _seed_chattahoochee(accounts, user, now, seed)
    for i, spec in enumerate(STREAM_FORESTS):
        if spec[0] not in have:
            _seed_stream_forest(accounts, user, spec, now, np.random.default_rng(seed + i))
    return user


def _only_demo_data(accounts: Accounts, forest) -> bool:
    repo = accounts.pipeline(forest).repo
    return not repo.query("SELECT 1 FROM observations WHERE model_version IS NULL OR model_version != 'demo_seed' "
                          "LIMIT 1")


def _add_visit(repo, tid: str, ts: float, lat: float, lon: float, sev: int, signs: list[str],
               sensors: dict | None, emb: np.ndarray, first: bool) -> None:
    oid = repo.add_observation(ObservationRecord(
        uuid.uuid4().hex, tid, ts, "new" if first else "existing", SPECIES, 0.95, None if first else 0.97,
        emb, lat, lon, 5.0, "demo_seed", {}, {"demo_seed": True}))
    health.set_health(repo, oid, sev, None)
    if sensors:
        field.set_sensors(repo, oid, sensors, "demo_seed")
    field.set_signs(repo, oid, signs)
    field.set_findings(repo, oid, diseases.assess(signs, sensors, sev, ts))


def _signs(sev: int, rng, ehs: bool, dry: bool) -> list[str]:
    s = []
    if sev >= 1 and rng.random() < 0.85:
        s.append("hwa_wool")
    elif rng.random() < 0.7:
        s.append("twigs_checked_clean")
    if sev >= 2:
        s += ["gray_green_foliage", "needle_loss"] + (["no_new_growth", "branch_dieback"] if sev == 3 else [])
    if ehs:
        s += ["ehs_scale", "needle_yellow_banding"]
    if dry:
        s.append("drought_browning")
    return s


def _seed_chattahoochee(accounts: Accounts, user: User, now: float, seed: int) -> None:
    lat0, lon0, _ = geography.GEOGRAPHY[CHATTAHOOCHEE]
    forest = accounts.create_forest(user.user_id, CHATTAHOOCHEE, lat0, lon0)
    repo = accounts.pipeline(forest).repo
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    dim = accounts.runtime.embedding_dim
    for _ in range(CHATTAHOOCHEE_TREES):
        x, y, stream, _t = geography.point_near_stream(CHATTAHOOCHEE, rng)
        lon, lat = geography.to_lonlat(lat0, lon0, x, y)
        # HWA moves upstream from the west end; scale on Mulky Creek; drought on Shanty Branch
        hwa = min(3.0, max(0.0, (1500 - x) / 3000 * 3.3 + rng.gauss(0, 0.6)))
        if stream in ("Mulky Creek", "Shanty Branch"):
            hwa *= 0.6
        ehs_p = {"Mulky Creek": 0.75}.get(stream, 0.25 if x > 700 else 0.04)
        ehs = rng.random() < ehs_p
        dry_slope = stream == "Shanty Branch"
        visits = rng.randint(2, 4)
        first = now - rng.uniform(620, 720) * DAY
        tid = repo.create_tree(SPECIES, "H", first)
        emb = nrng.normal(0, 1, dim).astype(np.float32)
        emb /= np.linalg.norm(emb)
        for v in range(visits):
            ts = min(first + v * rng.uniform(150, 210) * DAY, now - rng.uniform(1, 20) * DAY)
            late = v / max(visits - 1, 1)  # 0 first visit .. 1 latest: everything worsens over time
            sev = hwa - (1 - late) * 1.1 + (0.8 * late if dry_slope else 0) + (0.5 * late if ehs else 0)
            sev = int(round(min(3, max(0, sev))))
            soil = rng.uniform(6, 14) if dry_slope else rng.uniform(24, 42)
            sensors = None
            if rng.random() < 0.8:
                sensors = {"soil_moisture_pct": round(soil, 1),
                           "air_temp_c": round(rng.gauss(29 if dry_slope else 23, 3), 1),
                           "humidity_pct": round(min(99, max(20, rng.gauss(45 if dry_slope else 72, 8))), 0),
                           "light_lux": round(rng.uniform(9000, 30000) if dry_slope else rng.uniform(600, 9000), 0)}
            dry = dry_slope and soil < 15 and rng.random() < 0.8
            _add_visit(repo, tid, ts, lat + rng.gauss(0, 2e-5), lon + rng.gauss(0, 2e-5), sev,
                       _signs(sev, rng, ehs and (v > 0 or rng.random() < 0.5), dry), sensors, emb, v == 0)
        if rng.random() < 0.12:
            repo.set_notes(tid, "near trail; treated with imidacloprid (demo note)")
    for name, bbox in geography.section_bboxes(CHATTAHOOCHEE).items():
        sections.create_section(repo, name, bbox)


def _seed_stream_forest(accounts: Accounts, user: User, spec, now: float, rng) -> None:
    name, lat0, lon0, n, bearing = spec
    forest = accounts.create_forest(user.user_id, name, lat0, lon0)
    repo = accounts.pipeline(forest).repo
    dim = accounts.runtime.embedding_dim
    b = math.radians(bearing)
    for _ in range(n):
        # hemlocks line a stream: spread along it, a few tens of metres either side
        along, across = rng.uniform(-450, 450), rng.normal(0, 35)
        dn, de = along * math.cos(b) - across * math.sin(b), along * math.sin(b) + across * math.cos(b)
        lat = lat0 + dn / 111_320
        lon = lon0 + de / (111_320 * math.cos(math.radians(lat0)))
        # infestation spreading from the downstream end
        base = np.clip((along + 450) / 900 * 3.2 + rng.normal(0, 0.7), 0, 3)
        visits = int(rng.integers(1, 4))
        first = now - rng.uniform(400, 720) * DAY
        tid = repo.create_tree(SPECIES, "H", first)
        for v in range(visits):
            ts = min(first + v * rng.uniform(120, 200) * DAY, now - DAY)
            sev = int(round(min(3, max(0, base - (visits - 1 - v) * 0.6))))
            emb = rng.normal(0, 1, dim).astype(np.float32)
            ehs = rng.random() < 0.18
            sensors = None
            if rng.random() < 0.75:
                dry = (450 - along) / 900  # 1 = upslope/driest end
                sensors = {"soil_moisture_pct": round(float(np.clip(32 - 22 * dry + rng.normal(0, 4), 3, 60)), 1),
                           "air_temp_c": round(float(rng.normal(24, 5)), 1),
                           "humidity_pct": round(float(np.clip(rng.normal(68, 12), 20, 99)), 0),
                           "light_lux": round(float(rng.uniform(800, 18000)), 0)}
            _add_visit(repo, tid, ts, lat + rng.normal(0, 3e-5), lon + rng.normal(0, 3e-5), sev,
                       _signs(sev, rng, ehs, False), sensors, emb / np.linalg.norm(emb), v == 0)
        if rng.random() < 0.15:
            repo.set_notes(tid, "near trail; treated with imidacloprid (demo note)")
