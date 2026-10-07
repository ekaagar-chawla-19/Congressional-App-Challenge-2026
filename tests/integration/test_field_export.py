"""Field workflow: app captures on different days -> export -> later-day evaluation."""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from tests.helpers import build, capture, tree_view  # noqa: E402

DAY = 86400.0


def test_export_and_later_day_evaluation(tmp_path):
    import evaluate_field
    import export_field_data

    from hemlock_sentinel.evaluation.splits import read_manifest
    from hemlock_sentinel.preprocessing import decode_image, to_network_input

    app = build(tmp_path)
    for t, seed in enumerate(range(100, 110)):
        r = app.identify(capture(app, [tree_view(seed, v, 0) for v in range(3)]), now=1.7e9 + t)
        assert r.status == "new"
        for k, days in enumerate((14, 90)):  # revisits on later days
            r = app.identify(capture(app, [tree_view(seed, v, k + 1) for v in range(3)]), now=1.7e9 + days * DAY + t)
            assert r.status == "existing", r.message
    out = tmp_path / "field"
    stats = export_field_data.export(str(tmp_path / "db.sqlite"), str(tmp_path / "blobs"), str(out),
                                     fractions=(0.4, 0.2, 0.4))
    assert stats["trees"] == 10 and stats["trees_with_repeat_visits"] == 10
    recs = read_manifest(out / "manifest.csv")
    assert len({r.session for r in recs}) >= 3 and all(Path(r.path).exists() for r in recs)
    splits = json.loads((out / "splits.json").read_text())
    assert not set(splits["train"]) & set(splits["test"])

    emb, _ = app.runtime.run(np.stack([to_network_input(decode_image(Path(r.path).read_bytes()), 64) for r in recs]))
    res = evaluate_field.evaluate(recs, emb, set(splits["test"]), app.cal, repeats=5)
    assert res["n_trees"] == 4 and res["later_day_top1"] >= 0.9
    assert set(res["by_days_elapsed"]) == {"8-60d", "61-180d"}
    assert res["decision"]["new"]["wrong"] == 0.0
