"""Request/response models of the mobile API (they define the OpenAPI contract)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["existing", "new", "uncertain", "rejected_species", "unsupported_species", "recapture"]
Action = Literal["done", "review", "capture_another_view", "retake"]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    status: Literal["ok"]
    demo: bool
    model_version: str
    face_blur: bool = Field(description="false = face detector missing; photos are stored unscreened")


class CalibrationInfo(BaseModel):
    target_false_match_rate: float | None
    species_threshold: float
    match_threshold: float
    provenance: dict


class ModelInfo(BaseModel):
    version: str
    demo: bool
    backbone: str | None
    embedding_dim: int
    image_size: int
    species_labels: list[str]
    reid_supported_species: list[str]
    calibration: CalibrationInfo


class ViewSpecOut(BaseModel):
    key: str
    title: str
    instruction: str
    required: bool
    identity_view: bool


class Protocol(BaseModel):
    views: list[ViewSpecOut]
    extra_trunk_views: list[ViewSpecOut]
    min_views: int
    max_views: int
    max_total_views: int
    max_image_bytes: int


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)


class Species(BaseModel):
    label: str
    name: str
    confidence: float


class Candidate(BaseModel):
    tree_id: str
    probability: float | None = None
    global_score: float | None = Field(None, description="cosine similarity of the multi-view embeddings")


class Consistency(BaseModel):
    per_view_top: list[str | None]
    agreement: float
    contradicting_views: list[int] = Field(description="1-based view numbers")


class ViewQuality(BaseModel):
    index: int
    view_type: str
    accepted: bool
    problems: list[str]
    warnings: list[str]
    metrics: dict[str, float]
    faces_blurred: int


class CaptureCreated(BaseModel):
    capture_id: str
    next_view: ViewSpecOut
    expires_in_s: int


class ViewAdded(BaseModel):
    view: ViewQuality
    accepted_views: int
    progress: float = Field(description="0..1 over the standard 5-view protocol")
    can_identify: bool
    next_view: ViewSpecOut | None


class CaptureState(BaseModel):
    capture_id: str
    views: list[ViewQuality]
    accepted_views: int
    can_identify: bool
    next_view: ViewSpecOut | None
    result: IdentifyResult | None


class IdentifyRequest(BaseModel):
    force_commit: bool = Field(False, description="store an uncertain result for review instead of asking for "
                                                  "another trunk view")
    location: Location | None = None


class IdentifyResult(BaseModel):
    status: Status
    action: Action = Field(description="what the app should do next")
    message: str
    tree_id: str | None
    observation_id: str | None = Field(description="set once the observation is stored")
    species: Species | None = None
    probability: float | None = Field(None, description="calibrated probability that tree_id is correct")
    candidates: list[Candidate] = []
    consistency: Consistency | None = None
    next_view: ViewSpecOut | None = None
    views: list[ViewQuality] = []
    timings_ms: dict[str, float] = {}


class AssignRequest(BaseModel):
    tree_id: str = Field(description='an existing tree ID (e.g. "H-001") or "new"', examples=["H-001", "new"])


class AssignResult(BaseModel):
    observation_id: str
    tree_id: str
    created_tree: bool


class ViewOut(BaseModel):
    view_index: int
    view_type: str
    image_url: str | None
    heading_deg: float | None


class Observation(BaseModel):
    observation_id: str
    tree_id: str | None
    timestamp: str = Field(description="ISO 8601, UTC")
    status: str = Field(description="existing | new | uncertain | rejected_species | unsupported_species | "
                                    "user_confirmed | user_corrected")
    species: str | None
    species_confidence: float | None
    match_probability: float | None
    location: Location | None
    model_version: str | None
    candidates: list[Candidate]
    views: list[ViewOut]


class ObservationPage(BaseModel):
    items: list[Observation]
    total: int
    limit: int
    offset: int


class TreeSummary(BaseModel):
    tree_id: str
    species: str
    name: str
    created_at: str
    last_seen_at: str
    observation_count: int
    notes: str | None
    thumbnail_url: str | None


class TreePage(BaseModel):
    items: list[TreeSummary]
    total: int
    limit: int
    offset: int


class TreeDetail(TreeSummary):
    observations: list[Observation]


class TreeUpdate(BaseModel):
    notes: str | None = Field(None, max_length=5000)


class MergeRequest(BaseModel):
    duplicate_tree_id: str = Field(description="tree to fold into this one; its ID is retired, never reused")


CaptureState.model_rebuild()
