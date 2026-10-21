"""AI-guided active scanning: after every photo, decide what evidence the scan still needs.

The pipeline re-ranks the registered trees with the photos taken so far (the same retrieval, fusion and
calibrated thresholds as the final decision, see HemlockSentinel.preview) and this policy turns the ranking
into one short instruction. It is rule-based on purpose: every request has a reason the user can see
(photo quality, species doubt, two trees still close, photos that disagree, a clear match or a clearly new
tree), and the next photo asked for depends on that reason, not on a fixed script.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..acquisition.protocol import ALL_VIEWS, MIN_VIEWS, ViewSpec, is_identity_view

MAX_IDENTITY_VIEWS = 6  # stop asking after this many trunk photos; the decision then stands as uncertain


@dataclass
class Preview:
    """The ranking with the photos so far (no decision is stored)."""
    n_views: int
    candidates: list[dict] = field(default_factory=list)  # [{tree_id, probability, global_score}] best first
    agreement: float | None = None  # share of photos whose own best tree is the leader
    view_leaders: list[str] = field(default_factory=list)
    species_ok: bool | None = None  # None: the model has no species check
    hemlock_probability: float | None = None
    gallery_trees: int = 0
    match_threshold: float = 0.5
    view_match_threshold: float | None = None


@dataclass
class Guidance:
    state: str  # start | retake | species_doubt | first_tree | confident | ambiguous | contradicting | likely_new | building
    title: str  # a few words, shown large
    detail: str  # one short sentence
    candidates: list[dict] = field(default_factory=list)
    next_view: ViewSpec | None = None
    ready: bool = False  # enough evidence to identify now
    needs_more: bool = False  # the policy asks for another trunk photo even after the minimum


def _pct(p: float) -> str:
    return f"{round(100 * p)}%"


def _unused(captured: set[str], keys: list[str]) -> ViewSpec | None:
    for k in keys:
        if k not in captured:
            return ALL_VIEWS[k]
    return None


STANDARD = ["trunk_north", "trunk_right", "trunk_right2"]
EXTRA = ["trunk_right3", "trunk_north_high", "trunk_low_close"]


def guide(pv: Preview, captured: set[str], last_problem: str | None = None) -> Guidance:
    """captured: view keys accepted so far; last_problem: why the last photo was rejected (if it was)."""
    n = pv.n_views
    standard_next = _unused(captured, STANDARD)
    top = pv.candidates[:3]

    if last_problem:
        what = last_problem.split(":")[0].split("(")[0].strip()
        return Guidance("retake", "Retake that photo", f"It was {what}.", top, None)
    if n == 0:
        return Guidance("start", "Photo 1 of 3", "Bark at chest height, filling the frame.", [], standard_next)
    if pv.species_ok is False and n >= 2:
        return Guidance("species_doubt", "Is this a hemlock?",
                        f"Bark looks {_pct(pv.hemlock_probability or 0)} hemlock. Move closer to the trunk.",
                        [], standard_next or _unused(captured, ["trunk_low_close"]))
    if pv.gallery_trees == 0:
        ready = n >= MIN_VIEWS
        return Guidance("first_tree", "First tree in this forest" if not ready else "Ready: new tree",
                        "It will be registered as new." if not ready else "Tap Identify to register it.",
                        [], None if ready else standard_next, ready)

    best = top[0] if top else None
    second = top[1] if len(top) > 1 else None
    p1 = best["probability"] if best else 0.0
    p2 = second["probability"] if second else 0.0
    more = n < MAX_IDENTITY_VIEWS
    extra_next = _unused(captured, EXTRA) if more else None

    # photos pointing at different trees: the scan probably mixes trees, or a photo is poor
    if n >= 2 and pv.agreement is not None and pv.agreement < 1.0 and len(set(pv.view_leaders)) > 1 and p1 >= 0.2:
        names = " and ".join(dict.fromkeys(pv.view_leaders))
        return Guidance("contradicting", "Photos disagree", f"They point to {names}. Stay on one trunk.",
                        top, standard_next or extra_next, False, True)
    if best and p1 >= pv.match_threshold and (p2 < 0.5 * p1):
        if n < MIN_VIEWS:
            return Guidance("confident", f"Looks like {best['tree_id']}",
                            f"{_pct(p1)} so far. {MIN_VIEWS - n} more to confirm.", top, standard_next)
        return Guidance("confident", f"Match: {best['tree_id']}", f"{_pct(p1)} confident. Tap Identify.", top,
                        None, True)
    if best and second and p1 >= 0.15 and p2 >= 0.5 * p1:
        detail = f"{best['tree_id']} {_pct(p1)} vs {second['tree_id']} {_pct(p2)}."
        if n < MIN_VIEWS:
            return Guidance("ambiguous", "Two trees still close", detail, top, standard_next)
        return Guidance("ambiguous", "Need one more view", detail + " Close-up next." if extra_next else detail, top,
                        _unused(captured, ["trunk_low_close"] + EXTRA) if more else None, not more, more)
    view_strong = pv.view_match_threshold is not None and best and best["global_score"] is not None and \
        best["global_score"] >= pv.view_match_threshold
    if not best or (p1 < 0.05 and not view_strong):
        if n < MIN_VIEWS:
            return Guidance("likely_new", "No match so far", f"Photo {n + 1} of {MIN_VIEWS} next.", top, standard_next)
        return Guidance("likely_new", "Looks like a new tree", "No registered tree is close. Tap Identify.", top,
                        None, True)
    lead = f"{_pct(p1)} so far" if p1 >= 0.1 else "Closest so far"  # a near-zero % reads as broken
    if n < MIN_VIEWS:
        return Guidance("building", f"{best['tree_id']} leads", f"{lead}. Photo {n + 1} next.", top, standard_next)
    if more:
        return Guidance("building", "Not sure yet", f"{best['tree_id']} leads ({lead.lower()}). One more view.", top,
                        extra_next, False, True)
    return Guidance("building", "Still uncertain", "Identify to save it for review.", top, None, True)


def identity_keys(views) -> set[str]:
    return {v.view_type for v in views if v.accepted and is_identity_view(v.view_type)}
