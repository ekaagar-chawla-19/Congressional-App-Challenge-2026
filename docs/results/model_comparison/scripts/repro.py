import numpy as np, sys
from eval import tid, nrm, ap, PATH
X = np.load(f"emb/{sys.argv[1]}_pru.npy"); ALL = sorted(set(tid))
def run(seed, contiguous, proto, distract):
    rng = np.random.default_rng(seed); tr = list(ALL); rng.shuffle(tr); un, kn = tr[:10], tr[10:]
    g, q = [], []
    for t in kn:
        ii = np.flatnonzero(tid == t); ii = ii[np.argsort(PATH[ii])] if contiguous else rng.permutation(ii); h = len(ii) // 2
        g += list(ii[:h]); q += list(ii[h:])
    if distract: g += [i for t in un for i in np.flatnonzero(tid == t)][:0]
    g = np.array(g); q = np.array(q); s = X[q] @ X[g].T
    m = np.nanmean([ap(s[i], tid[g] == tid[j]) for i, j in enumerate(q)])
    names = sorted(kn)
    if proto: P = nrm(np.stack([X[g][tid[g] == t].mean(0) for t in names])); ts = X[q] @ P.T
    else: ts = np.stack([s[:, tid[g] == t].max(1) for t in names], 1)
    return m, (np.array(names)[ts.argmax(1)] == tid[q]).mean()
for c in (0, 1):
    for p in (0, 1):
        r = np.array([run(s, c, p, 0) for s in range(5)]).mean(0); print(f"contiguous={c} prototype={p}: mAP={r[0]:.3f} top1={r[1]:.3f}")
