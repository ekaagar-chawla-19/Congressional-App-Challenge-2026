"""Full-size download of observations with exactly one bark photo: distinct hemlocks used as distractors / new trees."""
import json, io, urllib.request, concurrent.futures as cf
from PIL import Image
OUT = "/home/user/data/inat_hemlock"; obs = {o["id"]: o for o in json.load(open(f"{OUT}/obs_all.json"))}
bark = {int(k): v for k, v in json.load(open(f"{OUT}/bark_thumbs.json")).items()}
jobs = [(oid, ii[0], obs[oid]["photos"][ii[0]].replace("square", "large")) for oid, ii in bark.items() if len(ii) == 1]
def save(j):
    oid, i, u = j
    try: im = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "hemlock-sentinel-eval"}), timeout=30).read())).convert("RGB")
    except Exception: return None
    if min(im.size) < 400: return None
    p = f"{OUT}/img/{oid}_{i}.jpg"; im.save(p, quality=92); return (p, oid, i)
with cf.ThreadPoolExecutor(16) as ex: keep = [r for r in ex.map(save, jobs) if r]
json.dump(keep, open(f"{OUT}/bark_single.json", "w")); print("done single", len(keep), "of", len(jobs))
