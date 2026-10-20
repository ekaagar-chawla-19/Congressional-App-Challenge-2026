"""Both models behind one interface: embed(list of RGB uint8 arrays) -> L2-normalised embeddings.
The friend's checkpoint is loaded as-is (read-only file, weights never modified, eval mode)."""
import hashlib, json
import cv2, numpy as np, torch, timm

MEAN = np.array([0.485, 0.456, 0.406], np.float32); STD = np.array([0.229, 0.224, 0.225], np.float32)

def _norm(img):  # HWC uint8 RGB -> CHW float
    return ((img.astype(np.float32) / 255 - MEAN) / STD).transpose(2, 0, 1)

class Friend:
    """ekaagar-chawla-19 RTX 3060 run: DINOv2 ViT-S/14, CLS+mean pooling -> Linear(768,256) -> BN, cosine."""
    def __init__(self, path, five_crop=True):
        ck = torch.load(path, map_location="cpu", weights_only=False)
        cfg = ck["config"]; self.cfg = cfg
        self.size, self.resize = cfg["train"]["img_size"], cfg.get("eval", {}).get("resize", 640 if cfg["train"]["img_size"] == 448 else 320)
        self.backbone = timm.create_model(cfg["model"]["backbone"], pretrained=False, num_classes=0, img_size=self.size)
        self.neck = torch.nn.Sequential(torch.nn.Linear(768, cfg["model"]["embed_dim"], bias=False), torch.nn.BatchNorm1d(cfg["model"]["embed_dim"]))
        sd = ck["model"]
        mb = self.backbone.load_state_dict({k[9:]: v for k, v in sd.items() if k.startswith("backbone.")}, strict=True)
        self.neck.load_state_dict({k[5:]: v for k, v in sd.items() if k.startswith("neck.")}, strict=True)
        self.backbone.eval(); self.neck.eval(); self.five = five_crop
        self.sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        torch.set_grad_enabled(False)

    def crops(self, img):
        h, w = img.shape[:2]; s = self.resize / min(h, w)
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        h, w = img.shape[:2]; c = self.size
        pos = [((h - c) // 2, (w - c) // 2)]
        if self.five: pos += [(0, 0), (0, w - c), (h - c, 0), (h - c, w - c)]
        return [img[y:y + c, x:x + c] for y, x in pos]

    def embed(self, imgs, bs=8):
        out = []
        for img in imgs:
            x = torch.from_numpy(np.stack([_norm(c) for c in self.crops(img)]))
            tok = self.backbone.forward_features(x)  # (n, 1+P, 384), final norm applied
            f = torch.cat([tok[:, 0], tok[:, 1:].mean(1)], 1)
            e = torch.nn.functional.normalize(self.neck(f), dim=1).mean(0)
            out.append(torch.nn.functional.normalize(e, dim=0).numpy())
        return np.stack(out)

class Ours:
    """The production model in the app (models/production/hemlock.onnx), with the app's own preprocessing."""
    def __init__(self, root):
        from hemlock_sentinel.app.server import load_model
        from hemlock_sentinel.preprocessing import to_network_input
        self.rt, self.cal, _ = load_model(f"{root}/models/production/hemlock.onnx", f"{root}/models/production/calibration.json")
        self.prep = to_network_input
        self.sha = hashlib.sha256(open(f"{root}/models/production/hemlock.onnx", "rb").read()).hexdigest()

    def embed(self, imgs):
        out = []
        for img in imgs:
            e, _ = self.rt.run(self.prep(img, self.rt.input_size)[None])
            out.append(e[0] / np.linalg.norm(e[0]))
        return np.stack(out)

    def species(self, imgs):
        out = []
        for img in imgs:
            _, l = self.rt.run(self.prep(img, self.rt.input_size)[None]); out.append(l[0])
        return np.stack(out)
