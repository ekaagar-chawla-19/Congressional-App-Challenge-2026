"""Demo account with two North Georgia forests of PLACEHOLDER hemlocks.

The placeholder trees have plausible positions, visit dates and severity ratings
so the account overview and map can be shown, but they have no photos and their
embeddings are random (they never match a real capture). Everything is tagged
``demo_seed`` and the account is clearly named. Real captures made while signed in
as the demo user are stored and matched normally.
"""

from __future__ import annotations

import math
import time
import uuid

import numpy as np

from ..database.models import ObservationRecord
from . import diseases, field, health
from .accounts import Accounts, User

DEMO_EMAIL = "demo@hemlock.test"
DEMO_PASSWORD = "hemlock-demo"
FORESTS = [  # name, centre (approx.), number of placeholder trees, stream bearing (deg)
    ("Cloudland Canyon State Park (demo)", 34.8335, -85.4816, 28, 35.0),
    ("Cooper Creek, Chattahoochee NF (demo)", 34.7590, -84.0700, 20, 110.0),
]
DAY = 86400.0


def seed_demo(accounts: Accounts, now: float | None = None, seed: int = 7) -> User:
    """Idempotent: returns the existing demo user if already seeded."""
    user = accounts.find_user(DEMO_EMAIL)
    if user is not None:
        return user
    user = accounts.register(DEMO_EMAIL, DEMO_PASSWORD, "Demo Field Team")
    now = time.time() if now is None else now
    rng = np.random.default_rng(seed)
    dim = accounts.runtime.embedding_dim
    for name, lat0, lon0, n, bearing in FORESTS:
        forest = accounts.create_forest(user.user_id, name, lat0, lon0)
        repo = accounts.pipeline(forest).repo
        b = math.radians(bearing)
        for i in range(n):
            # hemlocks line a stream: spread along it, a few tens of metres either side
            along, across = rng.uniform(-450, 450), rng.normal(0, 35)
            dn, de = along * math.cos(b) - across * math.sin(b), along * math.sin(b) + across * math.cos(b)
            lat = lat0 + dn / 111_320
            lon = lon0 + de / (111_320 * math.cos(math.radians(lat0)))
            # infestation spreading from the downstream end
            base = np.clip((along + 450) / 900 * 3.2 + rng.normal(0, 0.7), 0, 3)
            visits = int(rng.integers(1, 4))
            first = now - rng.uniform(400, 720) * DAY
            tid = repo.create_tree("tsuga_canadensis", "H", first)
            for v in range(visits):
                ts = first + v * rng.uniform(120, 200) * DAY
                sev = int(round(min(3, max(0, base - (visits - 1 - v) * 0.6))))
                emb = rng.normal(0, 1, dim).astype(np.float32)
                oid = repo.add_observation(ObservationRecord(
                    uuid.uuid4().hex, tid, min(ts, now - DAY), "new" if v == 0 else "existing",
                    "tsuga_canadensis", 0.95, None if v == 0 else 0.97, emb / np.linalg.norm(emb),
                    lat + rng.normal(0, 3e-5), lon + rng.normal(0, 3e-5), 5.0, "demo_seed", {},
                    {"demo_seed": True}))
                health.set_health(repo, oid, sev, None)
                # placeholder field data: wool on most infested trees, scale on some, a drier upslope end
                signs = []
                if sev >= 1 and rng.random() < 0.85:
                    signs.append("hwa_wool")
                elif rng.random() < 0.6:
                    signs.append("twigs_checked_clean")
                if sev >= 2:
                    signs += ["gray_green_foliage", "needle_loss"] + (["no_new_growth"] if sev == 3 else [])
                if rng.random() < 0.18:
                    signs += ["ehs_scale", "needle_yellow_banding"]
                sensors = None
                if rng.random() < 0.75:
                    dry = (450 - along) / 900  # 1 = upslope/driest end
                    sensors = {"soil_moisture_pct": round(float(np.clip(32 - 22 * dry + rng.normal(0, 4), 3, 60)), 1),
                               "air_temp_c": round(float(rng.normal(24, 5)), 1),
                               "humidity_pct": round(float(np.clip(rng.normal(68, 12), 20, 99)), 0),
                               "light_lux": round(float(rng.uniform(800, 18000)), 0)}
                    field.set_sensors(repo, oid, sensors, "demo_seed")
                field.set_signs(repo, oid, signs)
                field.set_findings(repo, oid, diseases.assess(signs, sensors, sev, min(ts, now - DAY)))
            if rng.random() < 0.15:
                repo.set_notes(tid, "near trail; treated with imidacloprid (demo note)")
    return user
