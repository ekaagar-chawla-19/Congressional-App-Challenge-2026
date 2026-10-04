"""Species head on the shared re-ID embedding + validated "unknown" threshold.

The head is a multinomial logistic regression on the L2-normalised embedding,
i.e. exactly one nn.Linear in the deployed model: one backbone pass serves
both species gating and re-identification.

Splits: train trees -> fit; val trees + held-out species THO (Thuja) ->
choose C and the rejection threshold; test trees + held-out species EPR
(Picea rubens, never seen anywhere) -> report. Decisions are made per
observation (3 views, mean probability), as in the app.

Usage: python training/species/train_head.py --emb runs/reid/X/embeddings.npy --out runs/species/X
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from hemlock_sentinel.evaluation.metrics import classification_metrics
from hemlock_sentinel.evaluation.splits import make_observations, read_manifest
from hemlock_sentinel.reid.multiview import l2_normalize
from hemlock_sentinel.species.inference import softmax
from hemlock_sentinel.species.labels import SPECIES

VAL_UNKNOWN = "thuja_occidentalis"
TEST_UNKNOWN = "picea_rubens"


def obs_probs(model_w, model_b, recs, emb, tree_ids, views=3, seed=0):
    sel = [r for r in recs if r.tree_id in tree_ids]
    obs = make_observations(sel, views, seed)
    idx = {r.path: i for i, r in enumerate(recs)}
    P, y = [], []
    for o in obs:
        z = l2_normalize(emb[[idx[p] for p in o.paths]])
        P.append(softmax(z @ model_w.T + model_b).mean(0))
        y.append(recs[idx[o.paths[0]]].species)
    return np.array(P), y


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    emb = np.load(args.emb)
    z = l2_normalize(emb)
    lab = {s: i for i, s in enumerate(SPECIES)}
    tr = [i for i, r in enumerate(recs) if r.tree_id in set(splits["train"])]
    Xtr, ytr = z[tr], np.array([lab[recs[i].species] for i in tr])

    held = set(splits["held_out_species"])
    val_known = set(splits["val"])
    val_unk = {t for t in held if any(r.tree_id == t and r.species == VAL_UNKNOWN for r in recs)}
    test_unk = {t for t in held if any(r.tree_id == t and r.species == TEST_UNKNOWN for r in recs)}

    best = None
    for C in (0.3, 1.0, 3.0, 10.0, 30.0):
        lr = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xtr, ytr)
        W, b = lr.coef_, lr.intercept_
        P, y = obs_probs(W, b, recs, emb, val_known)
        acc = float(np.mean([SPECIES[i] == t for i, t in zip(P.argmax(1), y)]))
        if best is None or acc > best[0]:
            best = (acc, C, W, b)
    acc_val, C, W, b = best

    # Threshold: maximise balanced accuracy of {known & correctly classified -> accept} vs {unknown -> reject}
    Pk, yk = obs_probs(W, b, recs, emb, val_known)
    Pu, _ = obs_probs(W, b, recs, emb, val_unk)
    ck = Pk.max(1)[[SPECIES[i] == t for i, t in zip(Pk.argmax(1), yk)]]
    cu = Pu.max(1)
    cands = np.unique(np.r_[ck, cu])
    ba = [(0.5 * ((ck >= t).mean() + (cu < t).mean()), t) for t in cands]
    ba_best, thr = max(ba)

    def evaluate(known_ids, unk_ids, seed):
        P, y = obs_probs(W, b, recs, emb, known_ids, seed=seed)
        pred_closed = [SPECIES[i] for i in P.argmax(1)]
        pred_open = [p if c >= thr else "unknown" for p, c in zip(pred_closed, P.max(1))]
        Pu_, _ = obs_probs(W, b, recs, emb, unk_ids, seed=seed)
        unk_pred = [SPECIES[i] if c >= thr else "unknown" for i, c in zip(Pu_.argmax(1), Pu_.max(1))]
        hem = "tsuga_canadensis"
        tp = sum(p == hem and t == hem for p, t in zip(pred_open, y))
        fp_known = sum(p == hem and t != hem for p, t in zip(pred_open, y))
        fp_unk = sum(p == hem for p in unk_pred)
        return {
            "closed_set": classification_metrics(y, pred_closed, SPECIES),
            "with_rejection": classification_metrics(y, pred_open, SPECIES + ["unknown"]),
            "known_rejected_rate": float(np.mean([p == "unknown" for p in pred_open])),
            "unknown_species_rejected_rate": float(np.mean([p == "unknown" for p in unk_pred])),
            "n_unknown_obs": len(unk_pred),
            "hemlock_precision": tp / max(tp + fp_known + fp_unk, 1),
            "hemlock_recall": tp / max(sum(t == hem for t in y), 1),
            "unknown_species_called_hemlock": fp_unk,
        }

    res = {"C": C, "val_accuracy_closed": acc_val, "threshold": float(thr), "threshold_val_balanced_acc": ba_best,
           "val": evaluate(val_known, val_unk, 0), "test": evaluate(set(splits["test"]), test_unk, 1),
           "protocol": "observation = 3 views of one tree, mean softmax; trees identity-disjoint; "
                       f"val unknown species={VAL_UNKNOWN}, test unknown species={TEST_UNKNOWN} (never trained/tuned on)"}
    np.savez(out / "species_head.npz", W=W.astype(np.float32), b=b.astype(np.float32), labels=np.array(SPECIES),
             threshold=np.float32(thr))
    (out / "species_results.json").write_text(json.dumps(res, indent=2))
    t = res["test"]
    print(json.dumps({"C": C, "threshold": thr, "test_acc_closed": t["closed_set"]["accuracy"],
                      "test_macro_f1": t["closed_set"]["macro_f1"], "test_known_rejected": t["known_rejected_rate"],
                      "test_unknown_rejected": t["unknown_species_rejected_rate"],
                      "hemlock_p": t["hemlock_precision"], "hemlock_r": t["hemlock_recall"]}, indent=1))


if __name__ == "__main__":
    main()
