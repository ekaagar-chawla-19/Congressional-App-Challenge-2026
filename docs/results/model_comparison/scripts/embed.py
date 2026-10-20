"""Embed the 986 PRU images and the probe images with one model; cache to emb/<name>_*.npy."""
import sys, time, glob, csv, numpy as np, cv2, torch
sys.path.insert(0, "/home/user/Congressional-App-Challenge-2026/src"); sys.path.insert(0, sys.path[0])
from models import Friend, Ours
torch.set_num_threads(4)
which = sys.argv[1]; D = sys.path[1] if False else __import__("os").path.dirname(__file__); S = D + "/.."
rows = [r for r in csv.DictReader(open("/home/user/Congressional-App-Challenge-2026/runs/data/manifest.csv")) if r["species"] == "tsuga_canadensis"]
probes = sorted(glob.glob(S + "/e2e/bark/*.jpg")) + sorted(glob.glob(S + "/ood/imgs/*"))
def load(p):
    im = cv2.imread(p, cv2.IMREAD_COLOR); return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
synth = {"black": np.zeros((960, 720, 3), np.uint8), "gray": np.full((960, 720, 3), 128, np.uint8),
         "white": np.full((960, 720, 3), 255, np.uint8), "noise": np.random.default_rng(0).integers(0, 256, (960, 720, 3), dtype=np.uint8)}
m = {"ours": lambda: Ours("/home/user/Congressional-App-Challenge-2026"), "f448": lambda: Friend(S + "/friend/vits_448_best.pt"),
     "f224": lambda: Friend(S + "/friend/vits_224_best.pt")}[which]()
print(which, m.sha[:12], flush=True)
def run(imgs):
    E, L = [], []
    for im in imgs:
        E.append(m.embed([im])[0])
        if which == "ours": L.append(m.species([im])[0])
    return np.stack(E), (np.stack(L) if L else None)
t = time.time(); E, L = run([load(r["path"]) for r in rows[:20]]); dt = (time.time() - t) / 20
print(f"{dt*1000:.0f} ms/image (incl. decode)", flush=True)
pe, pl = run([load(p) for p in probes] + list(synth.values()))
np.save(f"{D}/emb/{which}_probe.npy", pe); open(f"{D}/emb/probe_names.txt", "w").write("\n".join([p.split("/")[-1] for p in probes] + list(synth)))
if pl is not None: np.save(f"{D}/emb/{which}_probe_logits.npy", pl)
out, lo = [], []
for i in range(0, len(rows), 50):
    e, l = run([load(r["path"]) for r in rows[i:i+50]]); out.append(e); lo.append(l); print(which, i, flush=True)
np.save(f"{D}/emb/{which}_pru.npy", np.concatenate(out))
if lo[0] is not None: np.save(f"{D}/emb/{which}_pru_logits.npy", np.concatenate(lo))
open(f"{D}/emb/{which}_meta.txt", "w").write(f"sha={m.sha}\nms_per_image={dt*1000:.1f}\n")
print("done", which)
