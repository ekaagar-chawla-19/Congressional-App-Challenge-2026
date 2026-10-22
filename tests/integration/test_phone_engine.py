"""The phone-only tree recognition (mobile/src/engine) gives the server's answers.

1. mobile/src/engine/ondevice.ts is the shared on-device port (client/src/ondevice.ts, parity-tested against the
   server on held-out hemlocks) byte for byte, apart from its Gallery type.
2. Run under Node with ONNX Runtime on the photo the server recorded (web/speedtest/reference.json), decoded the way
   the phone decodes it: same fingerprint (cosine >= 0.9995), same hemlock probability, exact fingerprint storage.

Not covered here: ONNX Runtime's React Native binding on an actual phone (see docs/phone_only.md)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOBILE = ROOT / "mobile"


def test_engine_copy_matches_shared_port():
    shared = (ROOT / "client/src/ondevice.ts").read_text()
    copy = (MOBILE / "src/engine/ondevice.ts").read_text()
    head = 'import type { components } from "./schema";\n\ntype Gallery = components["schemas"]["Gallery"];\n'
    assert head in shared
    before, after = shared.split(head)
    assert copy.startswith(before) and copy.endswith(after), "re-copy client/src/ondevice.ts into mobile/src/engine/"


def _node():
    n = shutil.which("node")
    if not n:
        return None
    v = subprocess.run([n, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return n if (int(v[0]), int(v[1])) >= (22, 7) else None


@pytest.mark.skipif(_node() is None, reason="needs Node 22.7+")
@pytest.mark.skipif(not (ROOT / "client/node_modules/onnxruntime-node").exists(), reason="run npm ci in client/")
@pytest.mark.skipif(not (ROOT / "models/production/hemlock.onnx").exists(), reason="needs the production model")
def test_phone_engine_matches_server_reference():
    res = subprocess.run([_node(), "--experimental-transform-types", "--no-warnings", "test/engine.mjs"], cwd=MOBILE,
                         capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["decoded"] == [1200, 1600] and out["accepted"] and not out["problems"]
    assert out["cosine"] >= 0.9995
    assert abs(out["hemlock"] - out["hemlock_ref"]) < 0.01
    assert out["codec_roundtrip_exact"]


@pytest.mark.skipif(_node() is None, reason="needs Node 22.7+")
@pytest.mark.skipif(not (ROOT / "client/node_modules/onnxruntime-node").exists(), reason="run npm ci in client/")
@pytest.mark.skipif(not (ROOT / "models/production/hemlock.onnx").exists(), reason="needs the production model")
def test_full_size_photo_decoded_at_server_scale(tmp_path):
    """A 12 MP camera photo: the phone shrinks it by the server's JPEG draft factor (to 756x1008) before decoding, so
    its fingerprint matches the server's. (Shrinking to 1280 px and halving to 640 instead gave cosine 0.98.)"""
    import numpy as np
    from PIL import Image

    from hemlock_sentinel.pipeline.runtime import OnnxRuntime
    from hemlock_sentinel.preprocessing import decode_image, to_network_input

    big = tmp_path / "big.jpg"
    Image.open(ROOT / "web/speedtest/sample.jpg").convert("RGB").resize((3024, 4032), Image.LANCZOS).save(big, quality=92)
    rgb = decode_image(big.read_bytes())
    rt = OnnxRuntime(ROOT / "models/production/hemlock.onnx")
    emb = rt.run(to_network_input(rgb, rt.input_size)[None])[0][0]
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"size": [rgb.shape[1], rgb.shape[0]], "embedding": (emb / np.linalg.norm(emb)).tolist()}))
    res = subprocess.run([_node(), "--experimental-transform-types", "--no-warnings", "test/engine_big.mjs", str(big), str(ref)],
                         cwd=MOBILE, capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["size"] == out["server_size"] == [756, 1008]
    assert out["cosine"] >= 0.999
