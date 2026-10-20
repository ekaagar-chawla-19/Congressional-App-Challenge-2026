"""Equal footing: same rule for every model (3-photo query vs 3-photo enrolment, nearest tree, cosine threshold).
Threshold set on the 9 PRU validation trees (neither model trained on them) for a target false-match rate on
never-enrolled trees, then applied unchanged to the 14 test trees."""
import json, numpy as np, os
from sklearn.metrics import roc_auc_score
from eval import tid, nrm, PATH, split
VAL = sorted(t for t in split["val"] if t.startswith("PRU")); TEST = sorted(t for t in split["test"] if t.startswith("PRU"))
def episodes(X, trees, n_unseen, seeds):
    out = []
    for seed in seeds:
        rng = np.random.default_rng(seed); tr = list(trees); rng.shuffle(tr); un, kn = tr[:n_unseen], tr[n_unseen:]
        G, gt = [], []
        for t in tr:
            ii = np.flatnonzero(tid == t); ii = ii[np.argsort(PATH[ii])]; h = len(ii) // 2
            if t in kn: G.append(nrm(X[rng.choice(ii[:h], 3, replace=False)].mean(0))); gt.append(t)
        G = np.stack(G); gt = np.array(gt)
        for t in tr:
            ii = np.flatnonzero(tid == t); ii = ii[np.argsort(PATH[ii])]; pool = ii[len(ii) // 2:] if t in kn else ii
            for _ in range(5):
                q = nrm(X[rng.choice(pool, 3, replace=False)].mean(0)); s = G @ q
                out.append((t in kn, gt[s.argmax()] == t, s.max()))
    a = np.array(out, dtype=float); return a[:, 0].astype(bool), a[:, 1].astype(bool), a[:, 2]
res = {}
for m in [m for m in ("ours", "f448", "f224") if os.path.exists(f"emb/{m}_pru.npy")]:
    X = np.load(f"emb/{m}_pru.npy")
    kv, okv, sv = episodes(X, VAL, 3, range(200)); kt, okt, st = episodes(X, TEST, 4, range(200))
    r = {"test_top1": float(okt[kt].mean()), "test_auroc_new_tree": float(roc_auc_score(kt, st))}
    for fmr in (0.01, 0.05, 0.10):
        th = float(np.quantile(sv[~kv], 1 - fmr))
        acc = st >= th
        r[f"FMR{int(fmr*100)}%"] = dict(threshold=round(th, 4), right=round(float((acc & okt)[kt].mean()), 3),
            wrong_tree=round(float((acc & ~okt)[kt].mean()), 3), new_tree_false_match=round(float(acc[~kt].mean()), 3))
    res[m] = r; print(m, json.dumps(r))
json.dump(res, open("report_fair.json", "w"), indent=1)
