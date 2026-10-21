"""iNaturalist Eastern hemlock bark set, in three stages:
1. metadata of every research-grade, wild observation with >= 2 photos
2. CLIP (neither model under test) on small thumbnails keeps close-up bark photos
3. full-size download for observations with >= 2 bark photos"""
import json, io, os, time, urllib.request, concurrent.futures as cf, torch, open_clip
from PIL import Image
OUT = "/home/user/data/inat_hemlock"; os.makedirs(f"{OUT}/img", exist_ok=True)
UA = {"User-Agent": "hemlock-sentinel-eval"}
def fetch(u, t=30): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read()
meta = f"{OUT}/obs_all.json"
if not os.path.exists(meta):
    obs, idb = [], None
    while True:
        u = "https://api.inaturalist.org/v1/observations?taxon_name=Tsuga%20canadensis&quality_grade=research&photos=true&captive=false&per_page=200&order=desc&order_by=id"
        if idb: u += f"&id_below={idb}"
        for a in range(5):
            try: r = json.loads(fetch(u))["results"]; break
            except Exception: time.sleep(10)
        else: break
        if not r: break
        idb = r[-1]["id"]
        obs += [{"id": o["id"], "user": o["user"]["login"], "date": o.get("observed_on"), "loc": o.get("location"),
                 "photos": [p["url"] for p in o["photos"]]} for o in r if len(o["photos"]) >= 2]
        if len(obs) % 2000 < 200: print("meta", len(obs), idb, flush=True)
        time.sleep(1.0)
    json.dump(obs, open(meta, "w"))
obs = json.load(open(meta)); print("observations with >=2 photos:", len(obs), flush=True)
m, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k"); m.eval(); tok = open_clip.get_tokenizer("ViT-B-32")
P = ["a close-up photo of tree bark", "a photo of conifer needles on a branch", "a photo of small pine cones", "a photo of a whole tree",
     "a photo of a forest", "a photo of cut wood or a stump", "a photo of a seedling", "a photo of a person", "a photo of moss or lichen", "a photo of an insect"]
with torch.no_grad(): T = m.encode_text(tok(P)); T = T / T.norm(dim=-1, keepdim=True)
def img(u):
    try: return Image.open(io.BytesIO(fetch(u))).convert("RGB")
    except Exception: return None
jobs = [(o["id"], i, u.replace("square", "small")) for o in obs for i, u in enumerate(o["photos"])]
bark = {}; torch.set_num_threads(4)
with cf.ThreadPoolExecutor(24) as ex:
    for c in range(0, len(jobs), 512):
        chunk = jobs[c:c + 512]; ims = list(ex.map(lambda j: img(j[2]), chunk))
        ok = [(j, im) for j, im in zip(chunk, ims) if im is not None]
        if ok:
            with torch.no_grad():
                f = m.encode_image(torch.stack([pre(im) for _, im in ok])); f = f / f.norm(dim=-1, keepdim=True); p = (100 * f @ T.T).softmax(-1)
            for (j, _), pp in zip(ok, p):
                if pp.argmax() == 0 and pp[0] > 0.6: bark.setdefault(j[0], []).append(j[1])
        if c % 5120 == 0: print("thumbs", c, "/", len(jobs), "bark photos", sum(map(len, bark.values())), flush=True)
json.dump(bark, open(f"{OUT}/bark_thumbs.json", "w"))
byid = {o["id"]: o for o in obs}
big = [(oid, i, byid[oid]["photos"][i].replace("square", "large")) for oid, ii in bark.items() if len(ii) >= 2 for i in ii]
print("full-size downloads:", len(big), "from", sum(len(ii) >= 2 for ii in bark.values()), "observations", flush=True)
keep = []
def save(j):
    oid, i, u = j; im = img(u)
    if im is None or min(im.size) < 400: return None
    p = f"{OUT}/img/{oid}_{i}.jpg"; im.save(p, quality=95); return (p, oid, i)
with cf.ThreadPoolExecutor(16) as ex:
    for r in ex.map(save, big):
        if r: keep.append(r)
json.dump(keep, open(f"{OUT}/bark.json", "w")); print("done", len(keep), flush=True)
