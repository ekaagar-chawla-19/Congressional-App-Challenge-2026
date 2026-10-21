"""Candidate scoring, multi-view consistency, and the existing/new decision.

Signals for a query observation against candidate tree c:

* ``global``    cosine of the aggregated query embedding to tree c (max over its
                stored observations)
* ``gap``       global(c) minus the best global score of any other tree
* ``agreement`` fraction of query views whose own top-1 tree is c
* ``local``     optional local (keypoint) match score, see local_matching.py
* ``structure`` optional depth/structural score, see local_matching.py

These are combined by a logistic calibrator fitted on validation pairs, giving
P(same tree). Weights are therefore learned, not hand-set; with only the global
score available the decision reduces to a calibrated cosine threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .calibration import Calibration

FEATURE_ORDER = ("global", "gap", "agreement", "local", "structure")


@dataclass
class ViewConsistency:
    per_view_top: list[str]
    per_view_candidate_score: list[float]
    agreement: float
    contradicting_views: list[int]

    @property
    def contradicted(self) -> bool:
        return len(self.contradicting_views) > 0


def view_consistency(view_tree_scores: np.ndarray, tree_names: list[str], candidate: str,
                     margin: float = 0.0) -> ViewConsistency:
    """view_tree_scores: (V, T) cosine of each query view to each gallery tree.

    A view contradicts candidate c when its own best tree t != c scores more
    than ``margin`` above its score for c. ``margin`` is calibrated so that
    genuine matches in validation rarely trip it.
    """
    s = np.asarray(view_tree_scores, dtype=np.float32)
    ci = tree_names.index(candidate)
    top = s.argmax(1)
    contra = [v for v in range(len(s)) if top[v] != ci and s[v, top[v]] - s[v, ci] > margin]
    return ViewConsistency(
        per_view_top=[tree_names[i] for i in top],
        per_view_candidate_score=s[:, ci].tolist(),
        agreement=float((top == ci).mean()),
        contradicting_views=contra,
    )


def candidate_features(agg_scores: np.ndarray, view_scores: np.ndarray, tree_names: list[str],
                       candidate: str, local: float | None = None,
                       structure: float | None = None, gap_floor: float | None = None) -> dict[str, float]:
    """gap_floor: score of a virtual competing tree (Calibration.gap_floor), so small forests get a real gap."""
    ci = tree_names.index(candidate)
    g = float(agg_scores[ci])
    others = np.delete(agg_scores, ci)
    best_other = float(others.max()) if len(others) else None
    if gap_floor is not None:
        best_other = gap_floor if best_other is None else max(best_other, gap_floor)
    gap = g - best_other if best_other is not None else g
    agreement = float((np.asarray(view_scores).argmax(1) == ci).mean())
    f = {"global": g, "gap": gap, "agreement": agreement}
    if local is not None:
        f["local"] = float(local)
    if structure is not None:
        f["structure"] = float(structure)
    return f


def feature_key(features: dict[str, float]) -> str:
    return "+".join(k for k in FEATURE_ORDER if k in features)


def match_probability(features: dict[str, float], cal: Calibration) -> tuple[float, str]:
    """Return (P(same), name of the calibrated model used).

    Uses the fuser fitted on exactly this feature subset; if none exists, drops
    optional signals until one does; falls back to the calibrated global
    threshold (returning 1/0 around it) if no fuser exists at all.
    """
    feats = dict(features)
    for drop in (None, "structure", "local"):
        if drop:
            feats.pop(drop, None)
        key = feature_key(feats)
        if key in cal.fusers:
            fz = cal.fusers[key]
            x = np.array([[feats[n] for n in fz.feature_names]])
            return float(fz.predict_proba(x)[0]), key
    return (1.0 if features["global"] >= cal.global_threshold else 0.0), "global_threshold"


@dataclass
class IdentityDecision:
    kind: str  # "existing" | "new" | "uncertain"
    tree_id: str | None
    probability: float
    candidates: list[dict] = field(default_factory=list)
    consistency: ViewConsistency | None = None
    reason: str = ""
    model: str = ""


def decide(candidate_feats: list[tuple[str, dict[str, float]]], cal: Calibration,
           view_scores: np.ndarray | None = None, tree_names: list[str] | None = None) -> IdentityDecision:
    """candidate_feats: [(tree_id, features)] for the top-k candidates (may be empty).

    view_scores/tree_names: (V, T) per-view tree scores; when given, the best
    candidate is checked for contradicting views before it is accepted.
    """
    if not candidate_feats:
        return IdentityDecision("new", None, 0.0, reason="empty gallery")
    scored = []
    for tid, f in candidate_feats:
        p, model = match_probability(f, cal)
        scored.append({"tree_id": tid, "probability": p, "model": model, **f})
    scored.sort(key=lambda d: d["probability"], reverse=True)
    best = scored[0]
    consistency = None
    if view_scores is not None and tree_names is not None:
        consistency = view_consistency(view_scores, tree_names, best["tree_id"], cal.view_contradiction_margin)
    if best["probability"] < cal.match_threshold:
        if view_scores is not None and tree_names is not None and cal.view_match_threshold is not None:
            vs = np.asarray(view_scores)
            v, t = np.unravel_index(int(vs.argmax()), vs.shape)
            if vs[v, t] >= cal.view_match_threshold:
                return IdentityDecision(
                    "uncertain", None, best["probability"], scored, consistency,
                    reason=f"view {v + 1} alone matches {tree_names[t]} but the full capture does not; "
                           "re-take the views of this tree", model=best["model"])
        return IdentityDecision("new", None, best["probability"], scored, consistency,
                                reason="no candidate passes the calibrated match threshold",
                                model=best["model"])
    if consistency is not None and consistency.contradicted:
        return IdentityDecision("uncertain", best["tree_id"], best["probability"], scored, consistency,
                                reason=f"views {consistency.contradicting_views} point to a different tree; "
                                       "capture another view", model=best["model"])
    return IdentityDecision("existing", best["tree_id"], best["probability"], scored, consistency,
                            model=best["model"])
