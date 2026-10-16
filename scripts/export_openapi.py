"""Write the API contract (accounts mode, the full API) to docs/api/openapi.json.
Then regenerate the TS client types:  cd client && npm run gen"""

import json
import tempfile
from pathlib import Path

from hemlock_sentinel.api.accounts import Accounts
from hemlock_sentinel.api.server import create_api
from hemlock_sentinel.app.server import load_model

out = Path(__file__).resolve().parents[1] / "docs/api/openapi.json"
runtime, cal, _ = load_model(None, None)
with tempfile.TemporaryDirectory() as d:
    spec = create_api(demo=True, accounts=Accounts(d, runtime, cal)).openapi()
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(spec, indent=2) + "\n")
print(f"wrote {out} ({len(spec['paths'])} paths)")
