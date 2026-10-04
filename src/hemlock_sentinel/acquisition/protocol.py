"""Guided multi-view capture protocol.

Viewpoint consistency matters for re-identification: the global embedding is
not rotation-invariant around the trunk, and local bark matching only works
when two captures overlap (we measured near-zero inliers between
non-overlapping bark regions of the same BarkNet tree, docs/experiments.md).
So the first view is anchored to a compass direction, and the next views step
around the tree in a fixed direction.

``identity_view`` marks views the current model was trained/validated on
(bark). Branching/canopy views are captured and stored for future training
and for the health work, but do not contribute to the identity embedding
until a model validated on them exists (configs/default.yaml).
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

MIN_VIEWS = sum(v.required for v in GUIDED_VIEWS)
MAX_VIEWS = len(GUIDED_VIEWS)


def spec_for(index: int) -> ViewSpec:
    return GUIDED_VIEWS[index]
