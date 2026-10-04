"""Guided multi-view capture protocol.

Viewpoint consistency matters for re-identification: the global embedding is
not rotation-invariant around the trunk, and local bark matching only works
when two captures overlap. So the first view is anchored to a compass
direction and the next views step around the tree in a fixed direction.

``identity_view`` marks views the current model was trained/validated on
(bark). Branching/canopy views are captured and stored for future training
and for the health work, but do not contribute to the identity embedding
until a model validated on them exists.

Extra trunk views are requested only when an identification is uncertain:
more trunk views is the measured lever for open-set acceptance (5 vs 3 views:
47 % vs 30 % of returning trees auto-accepted at a 5 % false-match rate on
BarkNet test hemlocks, docs/experiments.md E-views).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewSpec:
    key: str
    title: str
    instruction: str
    required: bool
    identity_view: bool


GUIDED_VIEWS: tuple[ViewSpec, ...] = (
    ViewSpec("trunk_north", "Front / trunk",
             "Stand on the NORTH side of the tree about 1 m away. Fill the frame with bark at chest height.",
             True, True),
    ViewSpec("trunk_right", "Rotate right",
             "Walk about a quarter-turn clockwise around the tree. Bark at chest height again.", True, True),
    ViewSpec("trunk_right2", "Rotate farther right",
             "Walk another quarter-turn clockwise. Bark at chest height.", True, True),
    ViewSpec("branching", "Branching structure",
             "Step back 3-5 m so the lower trunk and first branches are visible.", False, False),
    ViewSpec("canopy", "Canopy",
             "Point the camera up into the crown.", False, False),
)

EXTRA_TRUNK_VIEWS: tuple[ViewSpec, ...] = (
    ViewSpec("trunk_right3", "Extra trunk view",
             "Walk the last quarter-turn clockwise (west side). Bark at chest height.", False, True),
    ViewSpec("trunk_north_high", "Extra trunk view",
             "Back on the NORTH side: bark at head height.", False, True),
)

ALL_VIEWS = {v.key: v for v in GUIDED_VIEWS + EXTRA_TRUNK_VIEWS}
MIN_VIEWS = sum(v.required for v in GUIDED_VIEWS)
MAX_VIEWS = len(GUIDED_VIEWS)  # standard protocol length (progress ring = this)
MAX_TOTAL_VIEWS = len(ALL_VIEWS)


def spec_for(key: str) -> ViewSpec:
    return ALL_VIEWS[key]


def is_identity_view(key: str) -> bool:
    return key in ALL_VIEWS and ALL_VIEWS[key].identity_view


def next_view(captured: set[str], need_identity: bool = False) -> ViewSpec | None:
    """Next view to ask for: the standard protocol in order, or (when an identification
    was uncertain) the next unused extra TRUNK view."""
    if need_identity:
        for v in GUIDED_VIEWS[:MIN_VIEWS] + EXTRA_TRUNK_VIEWS:
            if v.key not in captured:
                return v
        return None
    for v in GUIDED_VIEWS:
        if v.key not in captured:
            return v
    return None
