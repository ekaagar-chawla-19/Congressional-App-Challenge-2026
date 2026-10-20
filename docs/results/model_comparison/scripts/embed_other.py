"""Embed a fixed sample of NON-hemlock bark (40 images per species, trees our model never trained on)."""
import sys, os, csv, json, random, numpy as np, cv2, torch
sys.path.insert(0, "/home/user/Congressional-App-Challenge-2026/src"); D = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, D)
from models import Friend, Ours
torch.set_num_threads(4)
R = "/home/user/Congressional-App-Challenge-2026/runs/data"
sp = json.load(open(f"{R}/splits.json")); ok = set(sp["test"]) | set(sp["held_out_species"])
rows = [r for r in csv.DictReader(open(f"{R}/manifest.csv")) if r["species"] != "tsuga_canadensis" and r["tree_id"] in ok and os.path.exists(r["path"])]
by = {}
for r in rows: by.setdefault(r["species"], []).append(r)
rng = random.Random(0); pick = []
for s in sorted(by): pick += rng.sample(by[s], min(40, len(by[s])))
which = sys.argv[1]
m = {"ours": lambda: Ours("/home/user/Congressional-App-Challenge-2026"), "f448": lambda: Friend(f"{D}/../friend/vits_448_best.pt"),
     "f224": lambda: Friend(f"{D}/../friend/vits_224_best.pt")}[which]()
E, L = [], []
for i, r in enumerate(pick):
    im = cv2.cvtColor(cv2.imread(r["path"]), cv2.COLOR_BGR2RGB); E.append(m.embed([im])[0])
    if which == "ours": L.append(m.species([im])[0])
    if i % 50 == 0: print(which, "other", i, flush=True)
np.save(f"{D}/emb/{which}_other.npy", np.stack(E))
if L: np.save(f"{D}/emb/{which}_other_logits.npy", np.stack(L))
open(f"{D}/emb/other_meta.csv", "w").write("\n".join(f"{r['tree_id']},{r['species']}" for r in pick))
print("done other", which, len(pick))
