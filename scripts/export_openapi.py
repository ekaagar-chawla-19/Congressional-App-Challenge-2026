"""Write the API contract to docs/api/openapi.json (regenerate the TS client types from it)."""

import json
import tempfile
from pathlib import Path

from hemlock_sentinel.api.server import create_api
from hemlock_sentinel.app.server import build_pipeline

out = Path(__file__).resolve().parents[1] / "docs/api/openapi.json"
with tempfile.TemporaryDirectory() as d:
    pipe, _ = build_pipeline(f"{d}/db.sqlite", f"{d}/blobs", None, None)
    spec = create_api(pipe, demo=True).openapi()
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(spec, indent=2) + "\n")
print(f"wrote {out} ({len(spec['paths'])} paths)")
