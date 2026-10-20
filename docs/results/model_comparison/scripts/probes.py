"""Would each model claim a 'match' to an enrolled hemlock for photos that are NOT that tree?
Gallery: all 45 BarkNet hemlocks enrolled with every photo. One photo per query, each model's own k=1 threshold.
Ours also runs its real gates first (photo quality, then the species model)."""
import sys, os, csv, glob, numpy as np, cv2
sys.path.insert(0, "/home/user/Congressional-App-Challenge-2026/src"); D = os.path.dirname(os.path.abspath(__file__)); E = D + "/emb"
sys.path.insert(0, D)
from eval import ours_prob, cal, FTH, tid, nrm
from hemlock_sentinel.acquisition.quality import assess
S = D + "/.."
names = open(f"{E}/probe_names.txt").read().split("\n")
paths = sorted(glob.glob(S + "/e2e/bark/*.jpg")) + sorted(glob.glob(S + "/ood/imgs/*"))
synth = {"black": np.zeros((960, 720, 3), np.uint8), "gray": np.full((960, 720, 3), 128, np.uint8),
         "white": np.full((960, 720, 3), 255, np.uint8), "noise": np.random.default_rng(0).integers(0, 256, (960, 720, 3), dtype=np.uint8)}
imgs = [cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB) for p in paths] + list(synth.values())
qual = [assess(im).ok for im in imgs]
others = [l.split(",") for l in open(f"{E}/other_meta.csv").read().split("\n")] if os.path.exists(f"{E}/other_meta.csv") else []
names_t = sorted(set(tid))
def decide(m, Q, logits=None, quality=None):
    X = np.load(f"{E}/{m}_pru.npy"); code = np.array([names_t.index(t) for t in tid])
    s = Q @ X.T; ts = np.stack([s[:, code == c].max(1) for c in range(len(names_t))], 1)
    srt = np.sort(ts, 1); best, gap = srt[:, -1], srt[:, -2] - 0; gap = srt[:, -1] - srt[:, -2]
    if m == "ours":
        p = np.exp(logits - logits.max(1, keepdims=True)); p /= p.sum(1, keepdims=True)
        hem = (p.argmax(1) == 0) & (p[:, 0] >= cal["species_threshold"])
        fused = ours_prob(best, gap, np.ones_like(best))
        q = np.ones(len(Q), bool) if quality is None else np.array(quality)
        claim = q & hem & (fused >= cal["match_threshold"])
        return dict(best=best, claim=claim, quality_ok=q, hemlock=hem, hem_p=p[:, 0], fused=fused)
    return dict(best=best, claim=best >= FTH[m][1])
models = [m for m in ("ours", "f448", "f224") if os.path.exists(f"{E}/{m}_probe.npy") and os.path.exists(f"{E}/{m}_pru.npy")]
R = {}
for m in models:
    R[m] = decide(m, np.load(f"{E}/{m}_probe.npy"), np.load(f"{E}/ours_probe_logits.npy") if m == "ours" else None, qual)
print(f"{'probe':28}" + "".join(f"{m:>26}" for m in models))
for i, n in enumerate(names):
    row = f"{n:28}"
    for m in models:
        r = R[m]; tag = "MATCH(fake)" if r["claim"][i] else "no match"
        extra = (f" q={'ok' if r['quality_ok'][i] else 'REJ'} h={r['hem_p'][i]:.2f}") if m == "ours" else ""
        row += f"{r['best'][i]:>6.3f} {tag:11}{extra:>9}"
    print(row)
nonbark = [i for i, n in enumerate(names) if not n.startswith(("visit", "other"))]
for m in models:
    print(m, "non-bark/garbage probes claimed as a hemlock tree:", int(R[m]["claim"][nonbark].sum()), "/", len(nonbark))
if others:
    sp = np.array([o[1] for o in others])
    for m in models:
        if not os.path.exists(f"{E}/{m}_other.npy"): continue
        r = decide(m, np.load(f"{E}/{m}_other.npy"), np.load(f"{E}/ours_other_logits.npy") if m == "ours" else None)
        print(m, f"NON-HEMLOCK bark ({len(sp)} photos, {len(set(sp))} species) matched to a hemlock tree: {r['claim'].mean():.1%}",
              {s: round(float(r['claim'][sp == s].mean()), 2) for s in sorted(set(sp))})
        if m == "ours": print("   ours species gate alone lets through:", f"{r['hemlock'].mean():.1%}")
