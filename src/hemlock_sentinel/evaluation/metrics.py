"""Evaluation metrics: retrieval, open-set identification, species classification, calibration.

All functions take plain numpy arrays so they can be reused by tests,
training-time validation and the evaluation scripts.
"""

from __future__ import annotations

import numpy as np

from ..reid.multiview import l2_normalize


def retrieval_metrics(emb: np.ndarray, labels: np.ndarray, ks=(1, 5)) -> dict[str, float]:
    """One-vs-all retrieval (MiewID protocol): every image queries all others.

    Queries whose identity has no other image are skipped. Reports top-k
    accuracy and mAP.
    """
    z = l2_normalize(emb)
    s = z @ z.T
    np.fill_diagonal(s, -np.inf)
    labels = np.asarray(labels)
    order = np.argsort(-s, axis=1)
    out = {f"top{k}": 0.0 for k in ks}
    aps = []
    n = 0
    for i in range(len(z)):
        rel = labels[order[i]] == labels[i]
        rel = rel[:-1]  # last entry is the query itself (-inf)
        if not rel.any():
            continue
        n += 1
        for k in ks:
            out[f"top{k}"] += float(rel[:k].any())
        hits = np.cumsum(rel)
        aps.append(float((hits[rel] / (np.nonzero(rel)[0] + 1)).mean()))
    for k in ks:
        out[f"top{k}"] = out[f"top{k}"] / max(n, 1)
    out["mAP"] = float(np.mean(aps)) if aps else 0.0
    out["n_queries"] = n
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in out.items()}


def roc_auc(genuine: np.ndarray, impostor: np.ndarray) -> float:
    """Probability a random genuine score exceeds a random impostor score (ties count 1/2)."""
    g = np.asarray(genuine, dtype=np.float64)
    i = np.asarray(impostor, dtype=np.float64)
    if len(g) == 0 or len(i) == 0:
        return float("nan")
    allv = np.concatenate([g, i])
    ranks = _rankdata(allv)
    rg = ranks[: len(g)].sum()
    return float((rg - len(g) * (len(g) + 1) / 2) / (len(g) * len(i)))


def _rankdata(x: np.ndarray) -> np.ndarray:
    from scipy.stats import rankdata

    return rankdata(x)


def roc_curve(genuine: np.ndarray, impostor: np.ndarray, n: int = 200) -> dict[str, list[float]]:
    thr = np.linspace(min(np.min(genuine), np.min(impostor)), max(np.max(genuine), np.max(impostor)), n)
    tpr = [(np.asarray(genuine) >= t).mean() for t in thr]
    fpr = [(np.asarray(impostor) >= t).mean() for t in thr]
    return {"threshold": thr.tolist(), "tpr": tpr, "fpr": fpr}


def open_set_metrics(pred: list[str | None], truth: list[str | None]) -> dict[str, float]:
    """pred/truth: tree id, or None meaning "new tree".

    * false_match_rate: fraction of ALL queries assigned to a wrong existing tree
      (includes new trees matched to anything) — corrupts a tree's history.
    * false_new_rate: fraction of known-tree queries declared new — creates a duplicate.
    * known_accuracy / new_accuracy and precision / recall of the "existing" decision.
    """
    pred = list(pred)
    truth = list(truth)
    known = [i for i, t in enumerate(truth) if t is not None]
    new = [i for i, t in enumerate(truth) if t is None]
    wrong_match = sum(1 for i in range(len(truth)) if pred[i] is not None and pred[i] != truth[i])
    false_new = sum(1 for i in known if pred[i] is None)
    correct_existing = sum(1 for i in known if pred[i] == truth[i])
    n_pred_existing = sum(1 for p in pred if p is not None)
    return {
        "n_known": len(known),
        "n_new": len(new),
        "known_accuracy": correct_existing / max(len(known), 1),
        "new_accuracy": sum(1 for i in new if pred[i] is None) / max(len(new), 1),
        "false_match_rate": wrong_match / max(len(truth), 1),
        "false_match_rate_new_trees": sum(1 for i in new if pred[i] is not None) / max(len(new), 1),
        "false_new_rate": false_new / max(len(known), 1),
        "precision_existing": correct_existing / max(n_pred_existing, 1),
        "recall_existing": correct_existing / max(len(known), 1),
    }


def classification_metrics(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

    present = [l for l in labels if l in set(y_true) | set(y_pred)]
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=[l for l in present if l in set(y_true)],
                                   average="macro", zero_division=0)),
        "labels": present,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=present).tolist(),
        "n": len(y_true),
    }


def bootstrap_ci(values: np.ndarray, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    v = np.asarray(values, dtype=np.float64)
    if len(v) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(v, (n_boot, len(v)), replace=True).mean(1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))
