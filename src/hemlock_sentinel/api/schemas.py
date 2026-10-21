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
    models: list[str] = Field([], description="re-ID models this server runs (GET /api/v1/models for details)")


class CalibrationInfo(BaseModel):
    target_false_match_rate: float | None
    species_threshold: float
    match_threshold: float
    provenance: dict


class ModelFiles(BaseModel):
    """For running the model on the phone (onnxruntime-web / onnxruntime-react-native)."""
    onnx_url: str
    meta_url: str
    calibration_url: str
    onnx_bytes: int
    onnx_sha256: str


class ModelInfo(BaseModel):
    version: str
    on_device: ModelFiles | None = Field(None, description="null in demo mode (mock model)")
    demo: bool
    backbone: str | None
    embedding_dim: int
    image_size: int
    species_labels: list[str]
    reid_supported_species: list[str]
    calibration: CalibrationInfo


class ModelChoice(BaseModel):
    key: str = Field(description="send this as `model`: delta | gamma")
    name: str
    tagline: str
    description: str
    version: str
    checks_species: bool = Field(description="false = the model cannot tell species apart; it assumes a hemlock")
    embedding_dim: int
    image_size: int
    real_photo_top1: float | None = Field(None, description="share of real phone photos (2,371 iNaturalist "
                                                            "hemlocks) where the right tree was ranked first")
    speed: str | None = None
    default: bool
    demo: bool


class ModelList(BaseModel):
    default: str
    models: list[ModelChoice]


class CaptureCreate(BaseModel):
    model: str | None = Field(None, description="re-ID model for this capture: delta (default) or gamma")


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


class GalleryObservation(BaseModel):
    tree_id: str
    observation_id: str
    embedding_b64: str = Field(description="base64 of little-endian float32[embedding_dim], L2-normalised")


class Gallery(BaseModel):
    """A forest's stored tree fingerprints, for identifying trees on the phone (offline)."""
    model_version: str
    embedding_dim: int
    species: str
    tree_ids: list[str]
    observations: list[GalleryObservation]


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)


class Species(BaseModel):
    label: str
    name: str
    confidence: float
    hemlock_probability: float | None = Field(None, description="Eastern hemlock probability (all views fused)")
    threshold: float | None = Field(None, description="calibrated species threshold; below it the result is unknown")
    top: list[SpeciesScore] = Field([], description="most likely species, best first")


class SpeciesScore(BaseModel):
    label: str
    name: str
    probability: float


class SpeciesCheck(BaseModel):
    """Hemlock-or-not check of one photo (nothing is stored)."""
    is_hemlock: bool
    verdict: Literal["hemlock", "not_hemlock", "unsure"]
    hemlock_probability: float
    threshold: float
    species: SpeciesScore = Field(description="most likely species")
    top: list[SpeciesScore]
    quality: ViewQuality
    message: str


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
    hemlock_probability: float | None = Field(None, description="this photo alone (null if rejected before the model)")
    top_species: SpeciesScore | None = None


class CaptureCreated(BaseModel):
    capture_id: str
    model: str = Field(description="the re-ID model this capture runs")
    model_name: str
    next_view: ViewSpecOut
    expires_in_s: int


class GuidanceCandidate(BaseModel):
    tree_id: str
    probability: float = Field(description="calibrated P(this tree) with the photos so far")
    global_score: float | None = None


class Guidance(BaseModel):
    """AI-guided scanning: what the scan still needs after this photo (rule-based policy over the live ranking)."""
    state: Literal["start", "retake", "species_doubt", "first_tree", "confident", "ambiguous", "contradicting",
                   "likely_new", "building"]
    title: str = Field(description="a few words")
    detail: str = Field(description="one short sentence")
    candidates: list[GuidanceCandidate] = []
    next_view: ViewSpecOut | None = None
    ready: bool = Field(description="enough evidence to identify now")
    needs_more: bool = Field(description="the policy asks for another trunk photo beyond the minimum")


class ViewAdded(BaseModel):
    view: ViewQuality
    accepted_views: int
    progress: float = Field(description="0..1 over the standard 5-view protocol")
    can_identify: bool
    next_view: ViewSpecOut | None
    guidance: Guidance | None = None


class CaptureState(BaseModel):
    capture_id: str
    views: list[ViewQuality]
    accepted_views: int
    can_identify: bool
    next_view: ViewSpecOut | None
    result: IdentifyResult | None


Severity = Literal[0, 1, 2, 3]
SEVERITY_DOC = "observer's field rating: 0 none, 1 light, 2 moderate, 3 severe (NOT estimated by the model)"


class Sensors(BaseModel):
    """ESP32 sensor-node readings for one visit (any may be missing)."""
    soil_moisture_pct: float | None = Field(None, ge=0, le=100)
    air_temp_c: float | None = Field(None, ge=-40, le=60)
    humidity_pct: float | None = Field(None, ge=0, le=100)
    light_lux: float | None = Field(None, ge=0, le=200000)


SIGNS_DOC = "observed signs (keys from GET /api/v1/health-guide signs)"


class IdentifyRequest(BaseModel):
    force_commit: bool = Field(False, description="store an uncertain result for review instead of asking for "
                                                  "another trunk view")
    accept_best_guess: bool = Field(False, description="if uncertain, assign the top candidate (marked best_guess)")
    location: Location | None = None
    severity: Severity | None = Field(None, description=SEVERITY_DOC)
    health_notes: str | None = Field(None, max_length=2000)
    sensors: Sensors | None = None
    signs: list[str] = Field([], description=SIGNS_DOC)


class BestGuess(BaseModel):
    tree_id: str
    probability: float | None
    note: str


class Finding(BaseModel):
    condition: str
    name: str
    likelihood: float = Field(description="0-1")
    level: Literal["likely", "possible", "low", "unknown"]
    evidence: list[str]


class VisitCreate(BaseModel):
    """A visit without photos (e.g. ESP32 sensor reading at a known tree, or an observer check)."""
    sensors: Sensors | None = None
    signs: list[str] = Field([], description=SIGNS_DOC)
    severity: Severity | None = Field(None, description=SEVERITY_DOC)
    health_notes: str | None = Field(None, max_length=2000)
    location: Location | None = None


class SignsUpdate(BaseModel):
    signs: list[str] = Field(description=SIGNS_DOC)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    forest_id: int | None = Field(None, description="the forest the user is looking at (context)")
    tree_id: str | None = Field(None, description="the tree the user is looking at (context)")


class ChatReply(BaseModel):
    conversation_id: str
    reply: str
    tools_used: list[dict]
    stop_reason: str | None
    model: str


class IdentifyResult(BaseModel):
    status: Status
    model: str | None = Field(None, description="re-ID model that produced this result (delta | gamma)")
    model_name: str | None = None
    species_checked: bool = Field(True, description="false = this model has no species check; `species` is "
                                                    "null and the tree is assumed to be an Eastern hemlock")
    action: Action = Field(description="what the app should do next")
    message: str
    tree_id: str | None
    observation_id: str | None = Field(description="set once the observation is stored")
    species: Species | None = None
    probability: float | None = Field(None, description="calibrated probability that tree_id is correct")
    candidates: list[Candidate] = []
    consistency: Consistency | None = None
    next_view: ViewSpecOut | None = None
    best_guess: BestGuess | None = Field(None, description="top candidate when not auto-accepted, with confidence")
    findings: list[Finding] = Field([], description="health assessment of this visit")
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
    severity: int | None = Field(None, description=SEVERITY_DOC)
    health_notes: str | None = None
    has_photos: bool
    sensors: Sensors | None = Field(None, description="null = no ESP32 reading on this visit (N/A)")
    signs: list[str] = []
    findings: list[Finding] = []
    ai_inspection: dict | None = None
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
    main_condition: str | None = None
    severity: int | None = Field(None, description="most recent rating; " + SEVERITY_DOC)
    location: Location | None = None
    created_at: str
    last_seen_at: str
    observation_count: int
    notes: str | None
    thumbnail_url: str | None
    conditions: dict[str, Finding] = Field({}, description="latest assessed finding per condition")


class TreePage(BaseModel):
    items: list[TreeSummary]
    total: int
    limit: int
    offset: int


class SensorPoint(BaseModel):
    observation_id: str
    timestamp: str
    sensors: Sensors
    vpd_kpa: float | None = Field(None, description="vapour-pressure deficit from air temperature + humidity")


class Environment(BaseModel):
    summary: str = Field(description="the latest reading fused into one sentence")
    vpd_kpa: float | None
    water_stress: Literal["low", "some", "high"]
    changes: list[str] = Field([], description="versus the previous reading")


class TreeDetail(TreeSummary):
    current_conditions: list[Finding] = Field([], description="latest assessed finding per condition")
    latest_sensors: dict | None = None
    observations: list[Observation]
    sensor_history: list[SensorPoint] = Field([], description="visits with an ESP32 reading, newest first")
    environment: Environment | None = None
    since_last_visit: list[str] = Field([], description="what changed between the last two visits")
    next_action: str | None = None


class TreeUpdate(BaseModel):
    notes: str | None = Field(None, max_length=5000)


class MergeRequest(BaseModel):
    duplicate_tree_id: str = Field(description="tree to fold into this one; its ID is retired, never reused")


class HealthUpdate(BaseModel):
    severity: Severity | None = Field(None, description=SEVERITY_DOC)
    notes: str | None = Field(None, max_length=2000)


# ------------------------------------------------------------------ accounts
class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    user_id: int
    email: str
    name: str


class LoginResult(BaseModel):
    token: str = Field(description="send as header  Authorization: Bearer <token>")
    user: UserOut


class ForestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)


class ForestSummary(BaseModel):
    forest_id: int
    name: str
    center: Location | None
    tree_count: int
    observation_count: int
    severity_counts: dict[str, int] = Field(description="trees per latest rating: none/light/moderate/severe/unrated")
    last_visit_at: str | None


class AccountOverview(BaseModel):
    user: UserOut
    forests: list[ForestSummary]
    totals: dict[str, int]


class MapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict = Field(description='GeoJSON Point, coordinates [lon, lat]')
    properties: dict


class ForestMap(BaseModel):
    """GeoJSON FeatureCollection: one Point per tree with a known location (drop straight into a map library)."""
    type: Literal["FeatureCollection"] = "FeatureCollection"
    forest: ForestSummary | None
    severity_scale: dict[int, str]
    features: list[MapFeature]
    trees_without_location: list[str]


CaptureState.model_rebuild()
Species.model_rebuild()
SpeciesCheck.model_rebuild()


class SectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)


class Section(BaseModel):
    section_id: int
    name: str
    bbox: list[float] = Field(description="[west, south, east, north]")
    trees: int
    mean_severity: float | None
    pct_moderate_or_severe: float | None
    most_prominent_condition: str | None
    stress_score: float | None
    condition_counts: dict[str, int]
