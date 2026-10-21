"""Embed the images listed in sets/<name>.csv (path,tree_id) with one model -> emb/<model>_<name>.npy."""
import sys, os, csv, numpy as np, cv2, torch
sys.path.insert(0, "/home/user/Congressional-App-Challenge-2026/src"); D = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, D)
from models import Friend, Ours
torch.set_num_threads(4)
which, name = sys.argv[1], sys.argv[2]
rows = list(csv.reader(open(f"{D}/sets/{name}.csv")))
m = {"ours": lambda: Ours("/home/user/Congressional-App-Challenge-2026"), "f448": lambda: Friend(f"{D}/../friend/vits_448_best.pt"),
     "f224": lambda: Friend(f"{D}/../friend/vits_224_best.pt")}[which]()
part = f"{D}/emb/{which}_{name}.part.npz"
E, L = [], []
if os.path.exists(part): z = np.load(part); E, L = list(z["E"]), list(z["L"]); print("resuming at", len(E), flush=True)
for i, (p, _) in enumerate(rows):
    if i < len(E): continue
    im = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB); E.append(m.embed([im])[0])
    if which == "ours": L.append(m.species([im])[0])
    if i % 100 == 0: np.savez(part, E=np.stack(E), L=np.stack(L) if L else np.zeros((0,))); print(which, name, i, "/", len(rows), flush=True)
np.save(f"{D}/emb/{which}_{name}.npy", np.stack(E))
if L: np.save(f"{D}/emb/ours_{name}_logits.npy", np.stack(L))
os.remove(part) if os.path.exists(part) else None; print("done", which, name, flush=True)
