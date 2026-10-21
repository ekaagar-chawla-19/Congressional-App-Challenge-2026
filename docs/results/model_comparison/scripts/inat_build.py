"""bark.json -> cmp/sets/inat.csv (path, tree). Drops exact/near-duplicate photos within a tree, and drops observations
that are probably the same tree as an earlier one (same observer, within 25 m), so 'never enrolled' trees really are new."""
import json, csv, math, numpy as np, cv2
OUT = "/home/user/data/inat_hemlock"; obs = {o["id"]: o for o in json.load(open(f"{OUT}/obs_all.json"))}
keep = json.load(open(f"{OUT}/bark.json")); by = {}
for p, oid, i in sorted(keep, key=lambda r: (r[1], r[2])): by.setdefault(oid, []).append(p)
def thumb(p):
    g = cv2.resize(cv2.imread(p, cv2.IMREAD_GRAYSCALE), (32, 32)).astype(np.float32).ravel(); g -= g.mean(); return g / (np.linalg.norm(g) + 1e-6)
seen, rows, dup_trees, dup_photos = [], [], 0, 0
for oid in sorted(by):
    o = obs[oid]; loc = tuple(map(float, o["loc"].split(","))) if o.get("loc") else None
    if loc and any(u == o["user"] and math.dist(loc, l) * 111000 < 25 for u, l in seen): dup_trees += 1; continue
    if loc: seen.append((o["user"], loc))
    ps, th = [], []
    for p in by[oid]:
        t = thumb(p)
        if any(float(t @ x) > 0.97 for x in th): dup_photos += 1; continue
        ps.append(p); th.append(t)
    if len(ps) >= 2: rows += [(p, f"inat-{oid}") for p in ps]
csv.writer(open("/tmp/claude-0/-home-user-Congressional-App-Challenge-2026/94a0ed68-1ada-5e7d-b2b7-696da1881c08/scratchpad/cmp/sets/inat.csv", "w")).writerows(rows)
import collections; c = collections.Counter(r[1] for r in rows)
print(f"{len(c)} trees, {len(rows)} photos; dropped {dup_trees} likely-repeat trees, {dup_photos} near-duplicate photos;",
      "photos per tree:", sorted(collections.Counter(min(v, 6) for v in c.values()).items()))
