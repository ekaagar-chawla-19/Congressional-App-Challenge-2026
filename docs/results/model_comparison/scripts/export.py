"""Can the friend's frozen checkpoint run in the app's ONNX runtime unchanged? Export to scratch, compare outputs."""
import torch, numpy as np, onnxruntime as ort, os, hashlib
from models import Friend
f = Friend("../friend/vits_448_best.pt", five_crop=False)
class Net(torch.nn.Module):
    def __init__(s, f): super().__init__(); s.b, s.n = f.backbone, f.neck
    def forward(s, x):
        t = s.b.forward_features(x); return torch.nn.functional.normalize(s.n(torch.cat([t[:, 0], t[:, 1:].mean(1)], 1)), dim=1)
net = Net(f).eval(); x = torch.randn(2, 3, 448, 448)
torch.onnx.export(net, x, "f448.onnx", input_names=["image"], output_names=["embedding"], dynamic_axes={"image": {0: "n"}}, opset_version=17, dynamo=False)
y = net(x).numpy(); z = ort.InferenceSession("f448.onnx").run(None, {"image": x.numpy()})[0]
print("max abs diff torch vs onnx:", float(np.abs(y - z).max()), "size MB:", round(os.path.getsize("f448.onnx") / 1e6, 1))
print("checkpoint unchanged:", hashlib.sha256(open("../friend/vits_448_best.pt", "rb").read()).hexdigest()[:12])
