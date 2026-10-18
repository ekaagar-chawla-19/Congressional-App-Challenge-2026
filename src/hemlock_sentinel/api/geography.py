"""Map landmarks (streams, peaks, ridges, trails) for the demo forests.

The Chattahoochee forest is modelled on the Cooper Creek Scenic Area (Chattahoochee
National Forest, north Georgia): Cooper Creek with its tributaries, Yellow Mountain to the
north and Duncan Ridge to the south. Names come from the area; the shapes are drawn by hand
and only APPROXIMATE (good enough for a demo map, not for navigation). Hemlocks in the
southern Appalachians grow mostly in cool, moist stream corridors, so the demo trees are
placed along these streams (see demo_seed.py).

Geometry is written in metres east/north of the forest centre and converted to lon/lat.
"""

from __future__ import annotations

import math
import random

# name -> (centre lat, centre lon, features)
# feature: (kind, name, [(east_m, north_m), ...])  kinds: stream, ridge, trail, peak, place
GEOGRAPHY: dict[str, tuple[float, float, list[tuple[str, str, list[tuple[float, float]]]]]] = {
    "Cooper Creek Scenic Area, Chattahoochee NF (demo)": (34.7637, -84.0681, [
        ("stream", "Cooper Creek", [(1500, 420), (1200, 330), (950, 380), (700, 260), (450, 300), (250, 150),
                                    (0, 60), (-250, -30), (-500, 20), (-750, -110), (-1000, -150),
                                    (-1250, -290), (-1500, -330)]),
        ("stream", "Mulky Creek", [(500, 1300), (560, 1000), (470, 760), (420, 520), (250, 150)]),
        ("stream", "Bryant Creek", [(-600, -1250), (-680, -950), (-640, -700), (-720, -420), (-750, -110)]),
        ("stream", "Shanty Branch", [(1150, -700), (1080, -420), (1150, -150), (1200, 330)]),
        ("ridge", "Duncan Ridge", [(-1600, -1350), (-900, -1480), (-200, -1380), (500, -1520), (1300, -1400)]),
        ("peak", "Yellow Mountain", [(-950, 1150)]),
        ("trail", "Yellow Mountain Trail", [(-150, 40), (-320, 360), (-560, 660), (-800, 960), (-950, 1150)]),
        ("trail", "Mill Shoals Trail", [(100, 80), (320, -300), (520, -650), (680, -1000), (780, -1450)]),
        ("place", "Cooper Creek Campground", [(-60, 90)]),
    ]),
}

# Named sections drawn on the demo map: name -> (west, south, east, north) in metres from the centre.
SECTIONS: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "Cooper Creek Scenic Area, Chattahoochee NF (demo)": {
        "Lower Cooper Creek": (-1600, -500, -300, 300),
        "Upper Cooper Creek": (-300, -150, 1600, 460),
        "Mulky Creek": (250, 460, 750, 1400),
        "Bryant Creek": (-950, -1350, -450, -150),
        "Shanty Branch": (950, -800, 1350, 250),
    },
}


def to_lonlat(lat0: float, lon0: float, east: float, north: float) -> tuple[float, float]:
    return lon0 + east / (111_320 * math.cos(math.radians(lat0))), lat0 + north / 111_320


def landmarks(forest_name: str) -> dict:
    """GeoJSON FeatureCollection of a forest's landmarks (empty for forests without a drawn map)."""
    g = GEOGRAPHY.get(forest_name)
    feats = []
    if g:
        lat0, lon0, features = g
        for kind, name, pts in features:
            coords = [list(map(lambda v: round(v, 6), to_lonlat(lat0, lon0, e, n))) for e, n in pts]
            geom = {"type": "Point", "coordinates": coords[0]} if len(coords) == 1 else \
                {"type": "LineString", "coordinates": coords}
            feats.append({"type": "Feature", "geometry": geom, "properties": {"kind": kind, "name": name}})
    return {"type": "FeatureCollection", "approximate": True, "features": feats}


def section_bboxes(forest_name: str) -> dict[str, tuple[float, float, float, float]]:
    """name -> (west, south, east, north) in degrees."""
    g, secs = GEOGRAPHY.get(forest_name), SECTIONS.get(forest_name, {})
    if not g:
        return {}
    lat0, lon0, _ = g
    out = {}
    for name, (w, s, e, n) in secs.items():
        (lw, ls), (le, ln) = to_lonlat(lat0, lon0, w, s), to_lonlat(lat0, lon0, e, n)
        out[name] = (round(lw, 6), round(ls, 6), round(le, 6), round(ln, 6))
    return out


def point_near_stream(forest_name: str, rng: random.Random, spread_m: float = 22.0) -> tuple[float, float, str, float]:
    """Random point beside one of the forest's streams (longer streams more likely).
    Returns (east_m, north_m, stream name, position along that stream 0-1)."""
    _, _, features = GEOGRAPHY[forest_name]
    streams = [(name, pts) for kind, name, pts in features if kind == "stream"]
    lengths = [sum(math.dist(a, b) for a, b in zip(p, p[1:])) for _, p in streams]
    name, pts = rng.choices(streams, weights=lengths)[0]
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    t = rng.random()
    d = t * total
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if d <= seg:
            f = d / seg
            x, y = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
            nx, ny = -(b[1] - a[1]) / seg, (b[0] - a[0]) / seg  # unit normal
            off = rng.gauss(0, spread_m)
            return x + nx * off, y + ny * off, name, t
        d -= seg
    return pts[-1][0], pts[-1][1], name, 1.0
