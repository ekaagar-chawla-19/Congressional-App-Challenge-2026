"""Hemlock re-ID on iNaturalist phone photos. Each research-grade observation is one tree.
- 128 trees with >= 2 bark photos: enrolled with their first photo(s), queried with the rest; 25% never enrolled.
- 2,243 trees with one bark photo: half join the gallery as other trees in the forest, half are never-enrolled queries.
Queries are identical for every model (same seeds), so differences are paired; CIs resample the 128 trees."""
import sys, os, csv, json, numpy as np
from sklearn.metrics import roc_auc_score
D = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, D)
from eval import ours_prob, cal, FTH
MODELS = ("ours", "f448", "f224")

def load(name):
    rows = list(csv.reader(open(f"{D}/sets/{name}.csv"))); t = np.array([r[1] for r in rows])
    X = {m: np.load(f"{D}/emb/{m}_{name}.npy") for m in MODELS}
    lg = np.load(f"{D}/emb/ours_{name}_logits.npy"); P = np.exp(lg - lg.max(1, keepdims=True)); P /= P.sum(1, keepdims=True)
    return t, X, P
tm, Xm, Pm = load("inat"); ts_, Xs, Ps = load("inatsingle")
multi = sorted(set(tm)); idx = {t: np.flatnonzero(tm == t) for t in multi}  # csv keeps each tree's photo order
gate = lambda p: (p.argmax(-1) == 0) & (p[..., 0] >= cal["species_threshold"])

def run(m, seed, distractors):
    rng = np.random.default_rng(seed); tr = list(multi); rng.shuffle(tr); un = set(tr[:len(tr) // 4]); kn = [t for t in tr if t not in un]
    G = [Xm[m][idx[t][:len(idx[t]) // 2]] for t in kn]; names = [t for t in kn for _ in range(len(idx[t]) // 2)]
    perm = rng.permutation(len(ts_)); dg, dq = perm[:len(perm) // 2], perm[len(perm) // 2:]
    if distractors: G.append(Xs[m][dg]); names += list(ts_[dg])
    G = np.concatenate(G); names = np.array(names); uniq, code = np.unique(names, return_inverse=True)
    def score(q):
        s = G @ q; t = np.full(len(uniq), -9.0); np.maximum.at(t, code, s); o = np.argsort(-t)[:5]; return t[o], uniq[o]
    out = []
    queries = [(t, i, True) for t in kn for i in idx[t][len(idx[t]) // 2:]] + [(t, i, False) for t in un for i in idx[t]]
    for t, i, known in queries:
        s, n = score(Xm[m][i]); out.append((t, known, n[0] == t, s[0], s[0] - s[1], gate(Pm[i]), t in n))
    if distractors:
        for j in dq: s, n = score(Xs[m][j]); out.append((ts_[j], False, False, s[0], s[0] - s[1], gate(Ps[j]), False))
    return out

def metrics(rec, m):
    kn = np.array([r[1] for r in rec]); ok = np.array([r[2] for r in rec]); b = np.array([r[3] for r in rec], float)
    gap = np.array([r[4] for r in rec], float); hem = np.array([r[5] for r in rec]); t5 = np.array([r[6] for r in rec])
    th = np.quantile(b[~kn], 0.95)
    acc = hem & (ours_prob(b, gap, np.ones_like(b)) >= cal["match_threshold"]) if m == "ours" else b >= FTH[m][1]
    return {"top1": ok[kn].mean(), "top5": t5[kn].mean(), "auroc_new_tree": roc_auc_score(kn, b),
            "right@5%FM(equal)": ((b >= th) & ok)[kn].mean(), "shipped_right": (acc & ok)[kn].mean(),
            "shipped_wrong_tree": (acc & ~ok)[kn].mean(), "shipped_new_tree_matched": acc[~kn].mean()}

res = {"trees_matched": len(multi), "photos_matched": len(tm), "single_photo_trees": len(ts_),
       "ours_species_gate_accepts_real_hemlock_photos": round(float(np.concatenate([gate(Pm), gate(Ps)]).mean()), 3)}
for distractors in (False, True):
    tag = "with ~1,100 other trees in the forest" if distractors else "128-tree forest"
    R = {m: [r for s in range(10) for r in run(m, s, distractors)] for m in MODELS}
    pt = {m: metrics(R[m], m) for m in MODELS}
    by = {m: {} for m in MODELS}
    for m in MODELS:
        for r in R[m]: by[m].setdefault(r[0], []).append(r)
    multi_seen = [t for t in multi if t in by["ours"]]; single_seen = [t for t in by["ours"] if t not in set(multi)]
    rng = np.random.default_rng(1); boot = {m: [] for m in MODELS}
    for _ in range(200):
        s = list(rng.choice(multi_seen, len(multi_seen))) + single_seen  # resample the matched trees
        for m in MODELS: boot[m].append(metrics([r for t in s for r in by[m][t]], m))
    for m in MODELS:
        res[f"{tag} | {m}"] = {x: [round(float(pt[m][x]), 3), round(float(np.percentile([b[x] for b in boot[m]], 2.5)), 3),
                                   round(float(np.percentile([b[x] for b in boot[m]], 97.5)), 3)] for x in pt[m]}
    for o in ("f448", "f224"):
        res[f"{tag} | ours vs {o}"] = {x: {"diff": round(float(pt["ours"][x] - pt[o][x]), 3),
                                          "P(ours better)": round(float(np.mean([a[x] > c[x] for a, c in zip(boot["ours"], boot[o])])), 3)}
                                      for x in ("top1", "top5", "auroc_new_tree", "right@5%FM(equal)")}
json.dump(res, open(f"{D}/report_inat.json", "w"), indent=1)
for x, v in res.items(): print(x, v)
