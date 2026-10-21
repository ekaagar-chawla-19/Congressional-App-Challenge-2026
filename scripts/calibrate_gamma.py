"""Calibrate the app's decision thresholds for model gamma (weights untouched; post-hoc only).

Model gamma has no calibration for the app's decision logic (fused P(same tree), view checks,
duplicate-view checks), so this fits one the same way delta's was fitted, replaying the app's own
code: EmbeddingIndex retrieval (max over observations), candidate_features, LogisticCalibrator and
decide().

Data (gamma never trained on any hemlock):
* fit:     BarkNet PRU trees outside our test split (31) + half of the iNaturalist trees (by id parity)
* report:  the 14 BarkNet PRU test trees + the other half of the iNaturalist trees

BarkNet episodes look like the app: enrol a tree with 3 photos from the first half of its photo
sequence, query with 3 from the second half; a quarter of the trees are never enrolled.
iNaturalist: trees with >= 2 bark photos are enrolled with their first photo(s) and queried with the
rest; one-photo trees are other trees in the forest (half) or never-enrolled queries (half).

    python scripts/calibrate_gamma.py --cache <dir with gamma embeddings> --out models/gamma/calibration.json

The cache holds f448_pru.npy (manifest PRU rows in order), f448_inat.npy, f448_inatsingle.npy and
the sets/inat*.csv photo lists; see docs/results/model_comparison/scripts/.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
from pathlib import Path

import cv2
import numpy as np

from hemlock_sentinel.reid.calibration import Calibration, LogisticCalibrator, threshold_at_fmr
from hemlock_sentinel.reid.fusion import candidate_features, decide
from hemlock_sentinel.reid.multiview import aggregate_mean, l2_normalize
from hemlock_sentinel.reid.retrieval import EmbeddingIndex

FEATS = ["global", "gap", "agreement"]


def episodes_pru(X, tid, paths, trees, seeds, k=3, n_gallery=None):
    """n_gallery: enrol only this many trees (a new forest); the rest are never-enrolled queries."""
    for seed in seeds:
        rng = np.random.default_rng(seed)
        tr = list(trees)
        rng.shuffle(tr)
        un = set(tr[: len(tr) // 4] if n_gallery is None else tr[n_gallery:])
        gal, qs = [], []
        for t in tr:
            ii = np.flatnonzero(tid == t)
            ii = ii[np.argsort(paths[ii])]
            h = len(ii) // 2
            if t not in un:
                gal.append((t, aggregate_mean(X[rng.choice(ii[:h], k, replace=False)])))
            pool = ii if t in un else ii[h:]
            for _ in range(3):
                qs.append((t if t not in un else None, X[rng.choice(pool, k, replace=False)]))
        yield gal, qs


def episodes_inat(Xm, tm, Xs, ts, trees, singles, seeds, n_gallery=None):
    idx = {t: np.flatnonzero(tm == t) for t in trees}
    for seed in seeds:
        rng = np.random.default_rng(seed)
        tr = list(trees)
        rng.shuffle(tr)
        un = set(tr[: len(tr) // 4] if n_gallery is None else tr[n_gallery:])
        sp = rng.permutation(singles)
        dg, dq = (sp[: len(sp) // 2], sp[len(sp) // 2:]) if n_gallery is None else (sp[:0], sp[:200])
        gal = [(t, aggregate_mean(Xm[idx[t][: len(idx[t]) // 2]])) for t in tr if t not in un]
        gal += [(ts[j], l2_normalize(Xs[j])) for j in dg]
        qs = [(t, Xm[idx[t][len(idx[t]) // 2:]]) for t in tr if t not in un]
        qs += [(None, Xm[idx[t]]) for t in un] + [(None, Xs[[j]]) for j in dq]
        yield gal, qs


def features(gal, qs, top_k=5, gap_floor=None):
    """Per query: (true tree or None, [(candidate, features)], view_scores, names)."""
    index = EmbeddingIndex(len(gal[0][1]))
    index.add_many([g[0] for g in gal], np.stack([g[1] for g in gal]))
    names = index.tree_names()
    out = []
    for truth, views in qs:
        agg = aggregate_mean(views)
        s = index.tree_scores(agg)[0]
        vs = index.tree_scores(views)
        top = np.argsort(-s)[:top_k]
        out.append((truth, [(names[i], candidate_features(s, vs, names, names[i], gap_floor=gap_floor))
                                for i in top], vs, names))
    return out


def duplicate_thresholds(model: str, rows: list[dict], X: np.ndarray, tid: np.ndarray, paths: np.ndarray,
                         trees: list[str], n_reshoot: int = 30, seed: int = 0) -> dict:
    """Like scripts/calibrate_duplicate.py, re-shoots (camera jitter) vs genuine next views; but gamma scores the
    next view of a trunk close to a re-shoot, so the limits come from the full next-view distribution (every
    pair of neighbouring photos of the fit trees): reject above its 99.7th percentile (about 1 genuine view in
    300 is asked to move), warn above its 99th. Re-shoots below the limit pass and only weaken the capture."""
    from hemlock_sentinel.pipeline.runtime import GammaRuntime

    from calibrate_duplicate import jitter  # noqa: E402  (scripts/ is on sys.path when run as a script)

    nextv = []
    for t in trees:
        ii = np.flatnonzero(tid == t)
        ii = ii[np.argsort(paths[ii])]
        nextv += [float(X[a] @ X[b]) for a, b in zip(ii[:-1], ii[1:])]
    g = GammaRuntime(model)
    rng = random.Random(seed)
    reshoot = []
    for p in rng.sample([r["path"] for r in rows if r["tree_id"] in set(trees)], n_reshoot):
        a = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
        reshoot.append(float(g.embed_rgb(a)[0] @ g.embed_rgb(jitter(a, rng))[0]))
    hard, warn = float(np.percentile(nextv, 99.7)), float(np.percentile(nextv, 99))
    return {"hard": hard, "warn": warn, "next_view_cos_p50": float(np.median(nextv)), "n_next_view_pairs": len(nextv),
            "reshoot_cos_p1": float(np.percentile(reshoot, 1)), "reshoot_cos_median": float(np.median(reshoot)),
            "reshoots_caught_at_hard": float(np.mean(np.array(reshoot) > hard)), "n_reshoots": len(reshoot)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--manifest", default="runs/data/manifest.csv")
    ap.add_argument("--splits", default="runs/data/splits.json")
    ap.add_argument("--model", default="models/gamma/gamma.onnx")
    ap.add_argument("--target-fmr", type=float, default=0.01)
    ap.add_argument("--out", default="models/gamma/calibration.json")
    ap.add_argument("--skip-duplicate", action="store_true")
    ap.add_argument("--gap-floor-quantile", type=float, default=0.5,
                    help="virtual competitor = this quantile of the best other tree's score in a full stand")
    a = ap.parse_args()
    C = Path(a.cache)
    rows = [r for r in csv.DictReader(open(a.manifest)) if r["species"] == "tsuga_canadensis"]
    tid = np.array([r["tree_id"] for r in rows])
    paths = np.array([r["path"] for r in rows])
    Xp = np.load(C / "f448_pru.npy")
    split = json.load(open(a.splits))
    test = sorted(t for t in split["test"] if t.startswith("PRU"))
    fit_pru = sorted(set(tid) - set(test))
    im = list(csv.reader(open(C / "sets/inat.csv")))
    isg = list(csv.reader(open(C / "sets/inatsingle.csv")))
    tm, ts = np.array([r[1] for r in im]), np.array([r[1] for r in isg])
    Xm, Xs = np.load(C / "f448_inat.npy"), np.load(C / "f448_inatsingle.npy")
    half = lambda t: int(t.split("-")[1]) % 2  # noqa: E731
    im_fit = sorted(t for t in set(tm) if half(t) == 0)
    im_rep = sorted(t for t in set(tm) if half(t) == 1)
    s_fit = np.array([j for j, t in enumerate(ts) if half(t) == 0])
    s_rep = np.array([j for j, t in enumerate(ts) if half(t) == 1])

    def collect(pru_trees, inat_trees, singles, seeds, floor, small=(1, 2, 3, 5)):
        """Forests of every size: the full stand, and new forests holding only 1-5 enrolled trees."""
        out = []
        for n in (None, *small):
            sd = seeds if n is None else range(100 + (n or 0) * 1000, 100 + (n or 0) * 1000 + 3 * len(seeds))
            if pru_trees:
                for gal, qs in episodes_pru(Xp, tid, paths, pru_trees, sd, n_gallery=n):
                    out += features(gal, qs, gap_floor=floor)
            if inat_trees:
                for gal, qs in episodes_inat(Xm, tm, Xs, ts, inat_trees, singles, sd, n_gallery=n):
                    out += features(gal, qs, gap_floor=floor)
        return out

    # The virtual competitor: what the best OTHER tree scores in a full stand (median over queries).
    big = collect(fit_pru, im_fit, s_fit, range(20), None, small=())
    rivals = []
    for truth, cands, _, _ in big:
        other = [f["global"] for c, f in cands if c != truth]
        if other:
            rivals.append(max(other))
    gap_floor = float(np.quantile(rivals, a.gap_floor_quantile))
    fit = collect(fit_pru, im_fit, s_fit, range(20), gap_floor)
    X = np.array([[f[n] for n in FEATS] for _, cands, _, _ in fit for _, f in cands])
    y = np.array([int(c == truth) for truth, cands, _, _ in fit for c, _ in cands])
    fz = LogisticCalibrator(FEATS).fit(X, y)
    best_p = np.array([fz.predict_proba([[c[0][1][n] for n in FEATS]])[0] for _, c, _, _ in fit])
    best_ok = np.array([c[0][0] == truth for truth, c, _, _ in fit])
    imp = best_p[~best_ok]  # best candidate is the wrong tree, or the tree was never enrolled
    t_match = threshold_at_fmr(imp, a.target_fmr)
    best_g = np.array([c[0][1]["global"] for _, c, _, _ in fit])
    t_global = threshold_at_fmr(best_g[~best_ok], a.target_fmr)
    view_max = np.array([vs.max() for _, _, vs, _ in fit])
    unseen = np.array([truth is None for truth, _, _, _ in fit])
    t_view = threshold_at_fmr(view_max[unseen], 0.02)
    gaps = []
    for truth, c, vs, names in fit:
        if c[0][0] == truth and len(vs) > 1:
            ci = names.index(truth)
            gaps.append(float((vs.max(1) - vs[:, ci]).max()))
    margin = float(np.percentile(gaps, 99)) if gaps else 0.0
    dup = None if a.skip_duplicate else duplicate_thresholds(a.model, rows, Xp, tid, paths, fit_pru)
    cal = Calibration(species_threshold=0.0, match_threshold=float(t_match), global_threshold=float(t_global),
                      target_fmr=a.target_fmr, view_contradiction_margin=max(margin, 0.0),
                      view_match_threshold=float(t_view),
                      duplicate_cosine=dup["warn"] if dup else None, duplicate_hard_cosine=dup["hard"] if dup else None,
                      gap_floor=gap_floor, fusers={"+".join(FEATS): fz})

    def report(data):
        k = {"existing_right": 0, "existing_wrong": 0, "uncertain": 0, "new": 0}
        known, unseen_m, n_known, n_unseen = dict(k), 0, 0, 0
        for truth, cands, vs, names in data:
            d = decide(cands, cal, vs, names)
            if truth is None:
                n_unseen += 1
                unseen_m += d.kind == "existing"
            else:
                n_known += 1
                if d.kind == "existing":
                    known["existing_right" if d.tree_id == truth else "existing_wrong"] += 1
                else:
                    known[d.kind] += 1
        return {"known_tree_queries": n_known, **{x: round(v / n_known, 4) for x, v in known.items()},
                "never_enrolled_queries": n_unseen, "never_enrolled_matched": round(unseen_m / n_unseen, 4)}

    held = {"barknet_14_test_trees": report(collect(test, [], np.array([], int), range(20), gap_floor, small=())),
            "inaturalist_held_out_half": report(collect([], im_rep, s_rep, range(10), gap_floor, small=()))}
    for n in (1, 2, 5):
        held[f"new_forest_{n}_trees_barknet"] = report(
            [q for gal, qs in episodes_pru(Xp, tid, paths, test, range(5000, 5030), n_gallery=n)
             for q in features(gal, qs, gap_floor=gap_floor)])
        held[f"new_forest_{n}_trees_inaturalist"] = report(
            [q for gal, qs in episodes_inat(Xm, tm, Xs, ts, im_rep, s_rep, range(5000, 5030), n_gallery=n)
             for q in features(gal, qs, gap_floor=gap_floor)])
    cal.provenance = {
        "model": "gamma (vits_448_best.pt, weights unchanged)", "date": dt.date.today().isoformat(),
        "fitted_on": f"BarkNet PRU trees outside the test split ({len(fit_pru)}) + iNaturalist trees with even "
                     f"observation id ({len(im_fit)} multi-photo, {len(s_fit)} one-photo)",
        "n_fit_queries": len(fit), "n_fit_candidate_pairs": int(len(y)),
        "species_threshold": "not used: model gamma has no species head",
        "duplicate_views": dup, "held_out_decisions": held}
    cal.save(a.out)
    print(json.dumps({"gap_floor": gap_floor, "match_threshold": t_match, "global_threshold": t_global, "view_match_threshold": t_view,
                      "view_contradiction_margin": margin, "duplicate": dup, "held_out": held}, indent=1))


if __name__ == "__main__":
    main()
