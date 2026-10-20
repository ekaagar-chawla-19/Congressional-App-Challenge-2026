"""Score cached embeddings under identical protocols for every model."""
import sys, os, csv, json, numpy as np
sys.path.insert(0, "/home/user/Congressional-App-Challenge-2026/src")
from sklearn.metrics import roc_auc_score
from hemlock_sentinel.reid.calibration import Calibration
D = os.path.dirname(os.path.abspath(__file__)); E = D + "/emb"; R = "/home/user/Congressional-App-Challenge-2026"
rows = [r for r in csv.DictReader(open(f"{R}/runs/data/manifest.csv")) if r["species"] == "tsuga_canadensis"]
tid = np.array([r["tree_id"] for r in rows]); cap = np.array([r["capture"] for r in rows])
split = json.load(open(f"{R}/runs/data/splits.json")); TEST = sorted(t for t in split["test"] if t.startswith("PRU"))
TRAIN_OURS = set(split["train"]) | set(split["val"])
# Each model's own shipped thresholds (cosine, from its own validation set).
FTH = {"f448": {1: 0.7812, 3: 0.8198, 5: 0.8092}, "f224": {1: 0.7665, 3: 0.7864, 5: 0.794}}
cal = json.load(open(f"{R}/models/production/calibration.json"))
FZ = cal["fusers"]["global+gap+agreement"]

PATH = np.array([r["path"] for r in rows])
def nrm(x): return x / np.linalg.norm(x, axis=-1, keepdims=True)

def ours_prob(g, gap, agree):
    z = (np.stack(np.broadcast_arrays(g, gap, agree), -1) - FZ["mean"]) / FZ["scale"]
    return 1 / (1 + np.exp(-(z @ FZ["coef"] + FZ["intercept"])))

def ap(sims, rel):
    o = np.argsort(-sims); r = rel[o]; hits = np.cumsum(r)
    return float((hits / np.arange(1, len(r) + 1))[r].mean()) if r.any() else np.nan

def protocol(X, trees, n_unseen, seed, ks=(1, 3, 5), n_mv=5):
    """His protocol: n_unseen trees left out; each known tree's images split in half, gallery/query."""
    rng = np.random.default_rng(seed); trees = list(trees); rng.shuffle(trees)
    unseen, known = trees[:n_unseen], trees[n_unseen:]
    g_idx, q_by = [], {}
    for t in known:
        ii = np.flatnonzero(tid == t); ii = ii[np.argsort(PATH[ii])]; h = len(ii) // 2  # first/second half of the sequence, as he did
        g_idx += list(ii[:h]); q_by[t] = ii[h:]
    for t in unseen: q_by[t] = np.flatnonzero(tid == t)
    g_idx = np.array(g_idx); G = X[g_idx]; gt = tid[g_idx]; names = sorted(set(gt)); gcode = np.array([names.index(t) for t in gt])
    def tree_scores(Q):  # max over gallery images, like the app's retrieval index
        s = Q @ G.T; return np.stack([s[:, gcode == c].max(1) for c in range(len(names))], 1)
    out = {}
    # image mAP over gallery images, known k=1 queries
    qk = np.concatenate([q_by[t] for t in known]); s = X[qk] @ G.T
    out["mAP"] = float(np.nanmean([ap(s[i], gt == tid[q]) for i, q in enumerate(qk)]))
    for k in ks:
        Q, lab, views = [], [], []
        for t, ii in q_by.items():
            if k == 1: groups = [[i] for i in ii]
            else: groups = [rng.choice(ii, k, replace=False) for _ in range(n_mv)] if len(ii) >= k else []
            for gi in groups: Q.append(nrm(X[gi].mean(0))); lab.append(t); views.append(X[gi])
        Q = np.stack(Q); lab = np.array(lab); ts = tree_scores(Q); top = ts.argmax(1); best = ts.max(1)
        kn = np.isin(lab, known); pred = np.array(names)[top]
        srt = np.sort(ts, 1); gap = srt[:, -1] - srt[:, -2]
        agree = np.array([(tree_scores(v).argmax(1) == top[i]).mean() for i, v in enumerate(views)])
        top5 = np.array([lab[i] in np.array(names)[np.argsort(-ts[i])[:5]] for i in range(len(lab))])
        out[k] = dict(top1=float((pred[kn] == lab[kn]).mean()), top5=float(top5[kn].mean()),
                      auroc=float(roc_auc_score(kn, best)), n=int(kn.sum()), best=best, kn=kn, ok=pred == lab, gap=gap, agree=agree)
    return out

def summarise(name, X, trees, n_unseen, seeds):
    res = [protocol(X, trees, n_unseen, s) for s in seeds]
    line = {"mAP": np.mean([r["mAP"] for r in res])}
    for k in (1, 3, 5):
        for m in ("top1", "top5", "auroc"): line[f"{m}@{k}"] = float(np.mean([r[k][m] for r in res]))
        # open-set decision with the model's OWN shipped threshold
        acc_known = []; rej_unseen = []; wrong_acc = []
        for r in res:
            d = r[k]
            if name == "ours": accept = ours_prob(d["best"], d["gap"], d["agree"]) >= cal["match_threshold"]
            else: accept = d["best"] >= FTH[name][k]
            acc_known.append((accept & d["ok"])[d["kn"]].mean()); wrong_acc.append((accept & ~d["ok"])[d["kn"]].mean())
            rej_unseen.append((~accept)[~d["kn"]].mean())
        line[f"rightAccept@{k}"] = float(np.mean(acc_known)); line[f"wrongAccept@{k}"] = float(np.mean(wrong_acc))
        line[f"unseenRejected@{k}"] = float(np.mean(rej_unseen))
    return line

def capture_protocol(X, name, trees, n_unseen=4, seeds=range(20)):
    """Closer to the app: enrol each tree from 3 photos in the FIRST half of its photo sequence, query with 3 photos
    from the SECOND half (never neighbouring shots). n_unseen trees are never enrolled. Own shipped thresholds."""
    acc = []
    for seed in seeds:
        rng = np.random.default_rng(seed); tr = list(trees); rng.shuffle(tr); unseen, known = tr[:n_unseen], tr[n_unseen:]
        G, gt, Q, ql, QV = [], [], [], [], []
        for t in tr:
            ii = np.flatnonzero(tid == t); ii = ii[np.argsort(PATH[ii])]; h = len(ii) // 2
            if t in known: G.append(nrm(X[rng.choice(ii[:h], 3, replace=False)].mean(0))); gt.append(t)
            pool = ii[h:] if t in known else ii
            for _ in range(5): gi = rng.choice(pool, 3, replace=False); Q.append(nrm(X[gi].mean(0))); ql.append(t); QV.append(X[gi])
        G = np.stack(G); Q = np.stack(Q); ql = np.array(ql); gt = np.array(gt)
        ts = Q @ G.T; top = ts.argmax(1); best = ts.max(1); srt = np.sort(ts, 1); gap = srt[:, -1] - srt[:, -2]
        agree = np.array([((v @ G.T).argmax(1) == top[i]).mean() for i, v in enumerate(QV)])
        kn = np.isin(ql, gt); ok = gt[top] == ql
        accept = ours_prob(best, gap, agree) >= cal["match_threshold"] if name == "ours" else best >= FTH[name][3]
        acc.append(dict(top1=ok[kn].mean(), auroc=roc_auc_score(kn, best), rightAccept=(accept & ok)[kn].mean(),
                        wrongAccept=(accept & ~ok)[kn].mean(), unseenFalseMatch=accept[~kn].mean()))
    return {k: float(np.mean([a[k] for a in acc])) for k in acc[0]}

if __name__ == "__main__":
    models = [m for m in ("ours", "f448", "f224") if os.path.exists(f"{E}/{m}_pru.npy")]
    ALL = sorted(set(tid)); report = {}
    for m in models:
        X = np.load(f"{E}/{m}_pru.npy").astype(np.float32)
        report[m] = {
            "his_protocol_all45 (10 seeds)": summarise(m, X, ALL, 10, range(10)),
            "his_protocol_14_test_trees (20 seeds, 4 unseen)": summarise(m, X, TEST, 4, range(20)),
            "split_halves_14_test": capture_protocol(X, m, TEST),
            "split_halves_all45": capture_protocol(X, m, ALL, 10, range(10)),
        }
    json.dump(report, open(f"{D}/report_reid.json", "w"), indent=1)
    for m in report:
        for p, v in report[m].items(): print(m, "|", p, "|", {k: round(x, 3) for k, x in v.items()})
