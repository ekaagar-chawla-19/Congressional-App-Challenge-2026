"""Hemlock Sentinel mobile API (v1): the backend a React Native / Expo app talks to.

The phone takes the photos (and reads the ESP32 sensor node over Bluetooth LE); this server runs the trained model (ONNX), decides existing / new /
uncertain tree, and keeps the tree database. Interactive docs are served at /docs
and the machine-readable contract at /openapi.json. A demo forest map is at /map.

Run:  hemlock-api                       # accounts + forests, production model, demo account seeded
      hemlock-api --demo                # mock model, no weights needed
      hemlock-api --single              # one shared database, no sign-in (original mode)

Accounts mode: POST /auth/login -> token; send  Authorization: Bearer <token>  and
choose the forest with header  X-Forest-Id  (or ?forest_id=) on tree/capture calls.

Two ways to identify a tree:
* guided:   POST /captures -> POST /captures/{id}/views (one photo at a time, instant
            quality feedback) -> POST /captures/{id}/identify
* one-shot: POST /identify with all 3-7 photos in one multipart request.
Uncertain results are stored unassigned; resolve them with POST /observations/{id}/assign.

Two re-ID models can be chosen per capture (GET /models): delta (default, checks the species) and gamma
(448 px, best on real photos, no species check). Choose with {"model": "gamma"} on POST /captures, the
`model` form field on POST /identify, or the X-Model header. Every tree is fingerprinted by every model.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hmac
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..acquisition import privacy
from ..acquisition.interfaces import Frame, GeoFix
from ..acquisition.protocol import (
    EXTRA_TRUNK_VIEWS,
    GUIDED_VIEWS,
    MAX_TOTAL_VIEWS,
    MAX_VIEWS,
    MIN_VIEWS,
    ViewSpec,
    next_view,
    spec_for,
)
from ..app.server import SESSION_TTL_S, Sessions, build_pipeline
from ..database.models import ObservationRecord, TreeRecord
from ..pipeline.inference import HemlockSentinel, ObservationResult, ViewResult
from ..preprocessing import decode_image
from ..species.inference import softmax
from ..species.labels import COMMON_NAMES, ID_PREFIX, REID_SUPPORTED, SPECIES
from . import analysis as A
from . import diseases as D
from . import field as F
from . import geography as G
from . import health as H
from . import schemas as S
from . import sections as SEC
from ..pipeline.registry import DEFAULT_MODEL as DEFAULT_KEY
from ..pipeline.registry import ModelSpec, load_models
from ..pipeline.registry import spec as model_spec
from .accounts import Accounts, Forest, User
from .assistant import API_ERRORS, Assistant, NotConfigured

def _find_production(name: str) -> Path:
    """models/production/<name> next to the source checkout (pip install -e), else in the current
    directory (pip install . run from the repo root), else /app (Docker)."""
    rel = Path("models/production") / name
    for base in (Path(__file__).resolve().parents[3], Path.cwd(), Path("/app")):
        if (base / rel).exists():
            return base / rel
    return Path(__file__).resolve().parents[3] / rel


def _find_model(rel: str) -> Path:
    for base in (Path(__file__).resolve().parents[3], Path.cwd(), Path("/app")):
        if (base / rel).exists():
            return base / rel
    return Path(__file__).resolve().parents[3] / rel


DELTA_MODEL = _find_production("hemlock.onnx")
DELTA_CALIBRATION = _find_production("calibration.json")
GAMMA_MODEL = _find_model("models/gamma/gamma.onnx")
GAMMA_CALIBRATION = _find_model("models/gamma/calibration.json")
DEFAULT_MODEL, DEFAULT_CALIBRATION = DELTA_MODEL, DELTA_CALIBRATION  # older names
STATIC = Path(__file__).parent / "static"
MAX_IMAGE_BYTES = 25_000_000
PREFIX = "/api/v1"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


@dataclass
class Workspace:
    """Where a request reads and writes: one forest's tree database (or the single shared one)."""
    pipe: HemlockSentinel
    key: str
    user: User | None = None
    forest: Forest | None = None
    model: str = DEFAULT_KEY
    peers: dict | None = None  # every model's pipeline over this database

    @property
    def repo(self):
        return self.pipe.repo

    def invalidate(self, species: str | None = None) -> None:
        """Tree assignments changed: every model's retrieval index must reload."""
        for p in (self.peers or {self.model: self.pipe}).values():
            p.index.invalidate(species)


def _iso(t: float | None) -> str | None:
    return None if t is None else dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _image_url(key: str | None) -> str | None:
    return f"{PREFIX}/images/{key}" if key else None


def _spec(v: ViewSpec | None) -> S.ViewSpecOut | None:
    return S.ViewSpecOut(**asdict(v)) if v else None


def _species_scores(probs: dict[str, float], n: int = 3) -> list[S.SpeciesScore]:
    best = sorted(probs.items(), key=lambda kv: -kv[1])[:n]
    return [S.SpeciesScore(label=k, name=COMMON_NAMES.get(k, k), probability=round(float(p), 4)) for k, p in best]


def _view_quality(v: ViewResult) -> S.ViewQuality:
    out = S.ViewQuality(index=v.index, view_type=v.view_type, accepted=v.accepted, problems=v.quality.problems,
                        warnings=v.quality.warnings,
                        metrics={k: round(float(x), 4) for k, x in v.quality.metrics.items()},
                        faces_blurred=v.faces_blurred)
    if v.species_logits is not None:
        p = softmax(v.species_logits[None])[0]
        probs = {SPECIES[i]: float(p[i]) for i in range(len(SPECIES))}
        out.hemlock_probability = round(probs["tsuga_canadensis"], 4)
        out.top_species = _species_scores(probs, 1)[0]
    return out


def _candidates(raw: list[dict]) -> list[S.Candidate]:
    return [S.Candidate(tree_id=c["tree_id"],
                        probability=None if c.get("probability") is None else round(float(c["probability"]), 4),
                        global_score=None if c.get("global") is None else round(float(c["global"]), 4))
            for c in raw[:5]]


def _result(r: ObservationResult, action: str, views: list[ViewResult], nxt: ViewSpec | None = None) -> S.IdentifyResult:
    out = S.IdentifyResult(status=r.status, action=action, message=r.message, tree_id=r.tree_id,
                           observation_id=r.observation_id, next_view=_spec(nxt),
                           views=[_view_quality(v) for v in views],
                           timings_ms={k: round(v, 1) for k, v in r.timings_ms.items()})
    if r.species and r.species.checked:
        out.species = S.Species(label=r.species.species, name=r.species.common_name,
                                confidence=round(r.species.confidence, 4),
                                hemlock_probability=round(r.species.probabilities.get("tsuga_canadensis", 0.0), 4),
                                top=_species_scores(r.species.probabilities))
    if r.decision:
        out.probability = round(r.decision.probability, 4)
        out.candidates = _candidates(r.decision.candidates)
        c = r.decision.consistency
        if c:
            out.consistency = S.Consistency(per_view_top=list(c.per_view_top), agreement=round(c.agreement, 3),
                                            contradicting_views=[i + 1 for i in c.contradicting_views])
        if r.status == "uncertain" and out.candidates:
            top = out.candidates[0]
            pct = f"{top.probability:.0%}" if top.probability is not None else "unknown"
            out.best_guess = S.BestGuess(tree_id=top.tree_id, probability=top.probability,
                                         note=f"Most likely {top.tree_id} ({pct} confident). Not auto-accepted "
                                              "because it is below the validated threshold; confirm or pick another.")
    return out


def _finding(f: dict) -> S.Finding:
    return S.Finding(condition=f["condition"], name=D.CONDITIONS[f["condition"]]["name"],
                     likelihood=f["likelihood"], level=f["level"], evidence=f["evidence"])


def _location(lat, lon, acc=None) -> S.Location | None:
    if lat is None or lon is None:
        return None
    return S.Location(lat=lat, lon=lon, accuracy_m=None if acc is None or acc != acc else acc)


def _observations(repo, obs: list[ObservationRecord]) -> list[S.Observation]:
    hl = H.health_for(repo, [o.observation_id for o in obs])
    vd = F.visit_data(repo, [o.observation_id for o in obs])
    return [S.Observation(
        has_photos=any(v.image_key for v in o.views),
        sensors=S.Sensors(**{k: v for k, v in vd[o.observation_id]["sensors"].items() if k != "source"})
        if vd[o.observation_id]["sensors"] else None,
        signs=vd[o.observation_id]["signs"], findings=[_finding(f) for f in vd[o.observation_id]["findings"]],
        ai_inspection=vd[o.observation_id]["ai_inspection"],
        observation_id=o.observation_id, tree_id=o.tree_id, timestamp=_iso(o.timestamp), status=o.decision,
        severity=hl.get(o.observation_id, (None, None))[0], health_notes=hl.get(o.observation_id, (None, None))[1],
        species=o.species, species_confidence=o.species_confidence, match_probability=o.match_probability,
        location=_location(o.lat, o.lon, o.gps_accuracy_m), model_version=o.model_version,
        candidates=_candidates(o.metadata.get("candidates", [])),
        views=[S.ViewOut(view_index=v.view_index, view_type=v.view_type, image_url=_image_url(v.image_key),
                         heading_deg=v.heading_deg) for v in o.views]) for o in obs]


def _fix(loc: S.Location | None) -> GeoFix | None:
    return GeoFix(loc.lat, loc.lon, loc.accuracy_m if loc.accuracy_m is not None else float("nan")) if loc else None


def _form_sensors(**kw) -> dict | None:
    try:
        return F.clean_sensors(kw)
    except ValueError as e:
        raise ApiError(422, "invalid_request", str(e)) from e


def _check_signs(signs: list[str]) -> list[str]:
    bad = [x for x in signs if x not in D.SIGNS]
    if bad:
        raise ApiError(400, "unknown_sign", f"unknown sign(s) {bad}; see GET {PREFIX}/health-guide")
    return signs


def create_api(pipeline: HemlockSentinel | None = None, demo: bool = False, api_key: str | None = None,
               cors_origins: list[str] | None = None, accounts: Accounts | None = None,
               assistant: Assistant | None = None) -> FastAPI:
    """Single mode: pass ``pipeline`` (one shared database, no sign-in).
    Accounts mode: pass ``accounts`` (sign-in, one database per forest)."""
    if (pipeline is None) == (accounts is None):
        raise ValueError("pass exactly one of pipeline / accounts")
    app = FastAPI(title="Hemlock Sentinel API", version="1.1.0", description=__doc__.split("Run:")[0].strip())
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins or ["*"], allow_methods=["*"],
                       allow_headers=["*"])
    sessions = Sessions()
    # Retrieval indexes, ID allocation and corrections share in-memory state; the model
    # forward pass (the slow part, in add_view) runs outside this lock.
    db_lock = threading.Lock()
    runtime = pipeline.runtime if pipeline else accounts.runtime
    cal = pipeline.cal if pipeline else accounts.cal
    single_key = (pipeline.model_key or DEFAULT_KEY) if pipeline else None
    models: dict[str, ModelSpec] = accounts.models if accounts else {single_key: model_spec(single_key, runtime, cal, demo)}
    default_model = accounts.default_model if accounts else single_key
    blur_enabled = (pipeline.cfg if pipeline else accounts.config_factory()).blur_faces
    version = getattr(runtime, "version", "unknown")
    model_path = getattr(runtime, "model_path", None)
    model_files = None
    if model_path is not None and model_path.exists():
        import hashlib

        h = hashlib.sha256()
        with open(model_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        model_files = S.ModelFiles(onnx_url=f"{PREFIX}/model/files/hemlock.onnx",
                                   meta_url=f"{PREFIX}/model/files/hemlock.json",
                                   calibration_url=f"{PREFIX}/model/calibration",
                                   onnx_bytes=model_path.stat().st_size, onnx_sha256=h.hexdigest())
    if pipeline is not None:
        H.ensure_schema(pipeline.repo)
        F.ensure_schema(pipeline.repo)
    assistant = assistant or Assistant()

    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, e: ApiError):
        return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=e.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, e: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return JSONResponse({"error": {"code": code, "message": str(e.detail)}}, status_code=e.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, e: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(x) for x in err['loc'][1:])}: {err['msg']}" for err in e.errors())
        return JSONResponse({"error": {"code": "invalid_request", "message": msg}}, status_code=422)

    def require_key(request: Request):
        if api_key and not hmac.compare_digest(request.headers.get("x-api-key", ""), api_key):
            raise ApiError(401, "unauthorized", "missing or wrong X-API-Key header")

    def bearer(request: Request) -> str:
        h = request.headers.get("authorization", "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    bearer_scheme = HTTPBearer(auto_error=False, description="token from POST /api/v1/auth/login")

    def current_user(request: Request, _creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> User:
        if accounts is None:
            raise ApiError(404, "accounts_disabled", "server runs without accounts (--single)")
        user = accounts.user_for_token(bearer(request)) if bearer(request) else None
        if user is None:
            raise ApiError(401, "not_signed_in", "sign in first: POST /api/v1/auth/login, then send "
                                                 "Authorization: Bearer <token>")
        return user

    def get_forest(user: User, forest_id: int) -> Forest:
        f = accounts.forest(user.user_id, forest_id)
        if f is None:
            raise ApiError(404, "forest_not_found", f"no forest {forest_id} on this account")
        return f

    def check_model(key: str | None) -> str:
        key = (key or default_model).strip().lower()
        if key not in models:
            raise ApiError(400, "unknown_model", f"unknown model {key!r}; available: {', '.join(models)}")
        return key

    def pipe_for(ws: Workspace, key: str) -> HemlockSentinel:
        return ws.peers[key] if ws.peers and key in ws.peers else ws.pipe

    def model_result(out: S.IdentifyResult, key: str, pipe: HemlockSentinel) -> S.IdentifyResult:
        out.model, out.model_name = key, models[key].name
        if not pipe.checks_species:
            out.species, out.species_checked = None, False
            if out.status in ("existing", "new", "uncertain"):
                out.message += f" ({models[key].name} does not check the species; it assumes an Eastern hemlock.)"
        return out

    @contextmanager
    def model_ready(ws: Workspace, key: str):
        """This model's pipeline with its fingerprints of the forest up to date (and its lock held)."""
        if accounts is None or ws.forest is None:
            yield pipe_for(ws, key)
        else:
            with accounts.ready(ws.forest, key) as p:
                yield p

    def workspace(request: Request, _creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
                  x_forest_id: str | None = Header(None, description="forest to work in (accounts mode)"),
                  x_model: str | None = Header(None, description="re-ID model: delta (default) or gamma")) -> Workspace:
        model = check_model(x_model or request.query_params.get("model"))
        if pipeline is not None:
            return Workspace(pipeline, "single", model=model, peers={single_key: pipeline})
        user = current_user(request)
        raw = x_forest_id or request.query_params.get("forest_id")
        if not raw:
            raise ApiError(400, "forest_required", "choose a forest: header X-Forest-Id (or ?forest_id=); "
                                                   "list them with GET /api/v1/forests")
        try:
            fid = int(raw)
        except ValueError as e:
            raise ApiError(400, "forest_required", "X-Forest-Id must be a number") from e
        f = get_forest(user, fid)
        peers = accounts.pipelines(f)
        return Workspace(peers[model], f"{user.user_id}:{f.forest_id}", user, f, model, peers)

    errors = {r: {"model": S.ErrorResponse} for r in (400, 401, 404, 409, 413, 422)}
    api = APIRouter(prefix=PREFIX, dependencies=[Depends(require_key)], responses=errors)
    WS = Depends(workspace)

    # ----------------------------------------------------------------- shared
    def get_capture(cid: str, ws: Workspace) -> dict:
        try:
            s = sessions.get(cid)
        except StarletteHTTPException as e:
            raise ApiError(404, "capture_not_found", "capture not found or expired (30 min)") from e
        if s.get("owner") != ws.key:
            raise ApiError(404, "capture_not_found", "capture not found in this forest")
        return s

    def get_tree(ws: Workspace, tree_id: str) -> TreeRecord:
        t = ws.repo.get_tree(tree_id)
        if t is None:
            raise ApiError(404, "tree_not_found", f"unknown tree {tree_id}")
        if t.merged_into:
            raise ApiError(409, "tree_merged", f"{tree_id} was merged into {t.merged_into}")
        return t

    async def read_image(upload: UploadFile) -> tuple[bytes, object]:
        data = await upload.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise ApiError(413, "image_too_large", f"{upload.filename}: over {MAX_IMAGE_BYTES // 1_000_000} MB")
        try:
            return data, decode_image(data)
        except Exception as e:  # noqa: BLE001
            raise ApiError(400, "bad_image", f"{upload.filename}: cannot decode image ({e})") from e

    def add_view(ws: Workspace, views: list[ViewResult], data: bytes, rgb, view_key: str,
                 heading: float | None, model: str | None = None) -> ViewResult:
        prev = [v for v in views if v.view_type != view_key]
        return pipe_for(ws, model or ws.model).process_view(Frame(rgb, time.time(), encoded=data, heading_deg=heading), len(prev), prev,
                                    view_key=view_key)

    def check_view_key(key: str) -> None:
        try:
            spec_for(key)
        except KeyError as e:
            raise ApiError(400, "unknown_view", f"unknown view_key {key!r}; see GET {PREFIX}/protocol") from e

    def tree_summary(ws: Workspace, t: TreeRecord, status: dict | None = None,
                     thumb: str | None = None) -> S.TreeSummary:
        if thumb is None:
            thumb = next((v.image_key for v in ws.repo.gallery_views(t.tree_id) if v.image_key), None)
        if status is None:
            status = next((d for d in A.tree_profiles(ws.repo) if d["tree_id"] == t.tree_id), {})
        return S.TreeSummary(tree_id=t.tree_id, species=t.species, name=COMMON_NAMES.get(t.species, t.species),
                             main_condition=status.get("main_condition"), severity=status.get("severity"), location=_location(status.get("lat"), status.get("lon")),
                             created_at=_iso(t.created_at), last_seen_at=_iso(t.last_seen_at),
                             observation_count=t.observation_count, notes=t.notes, thumbnail_url=_image_url(thumb),
                             conditions={c: _finding(f) for c, f in status.get("conditions", {}).items()})

    def refresh_findings(ws: Workspace, oid: str) -> list[dict]:
        o = ws.repo.get_observation(oid)
        vd = F.visit_data(ws.repo, [oid])[oid]
        sev = H.health_for(ws.repo, [oid]).get(oid, (None, None))[0]
        findings = D.assess(vd["signs"], vd["sensors"], sev, o.timestamp, any(v.image_key for v in o.views),
                            F.ai_signs(vd["ai_inspection"]))
        F.set_findings(ws.repo, oid, findings)
        return findings

    def record_visit(ws: Workspace, oid: str | None, severity: int | None = None, notes: str | None = None,
                     sensors: dict | None = None, signs: list[str] | None = None) -> list[S.Finding]:
        if not oid:
            return []
        if severity is not None or notes:
            H.set_health(ws.repo, oid, severity, notes)
        if sensors:
            F.set_sensors(ws.repo, oid, sensors)
        if signs:
            F.set_signs(ws.repo, oid, _check_signs(signs))
        return [_finding(f) for f in refresh_findings(ws, oid)]

    def accept_best_guess_fn(ws: Workspace, r: ObservationResult) -> bool:
        if r.status != "uncertain" or not r.observation_id or not r.decision or not r.decision.candidates:
            return False
        top = r.decision.candidates[0]
        ws.repo.assign_observation(r.observation_id, top["tree_id"], "best_guess")
        ws.invalidate(r.species.species)
        r.tree_id = top["tree_id"]
        r.message = f"Assigned to best guess {top['tree_id']} ({top['probability']:.0%} confident); correct it " \
                    "from the tree page if wrong"
        return True

    def forest_summary(f: Forest) -> S.ForestSummary:
        repo = accounts.pipeline(f).repo
        status = H.tree_status(repo)
        n_obs, last = repo.query("SELECT COUNT(*), MAX(timestamp) FROM observations")[0]
        return S.ForestSummary(forest_id=f.forest_id, name=f.name, center=_location(f.lat, f.lon),
                               tree_count=len(status), observation_count=n_obs,
                               severity_counts=H.severity_counts(status), last_visit_at=_iso(last))

    def forest_map(ws: Workspace) -> S.ForestMap:
        status = A.tree_profiles(ws.repo)
        feats, missing = [], []
        for d in status:
            if d["lat"] is None:
                missing.append(d["tree_id"])
                continue
            thumb = next((v.image_key for v in ws.repo.gallery_views(d["tree_id"]) if v.image_key), None)
            feats.append(S.MapFeature(
                geometry={"type": "Point", "coordinates": [round(d["lon"], 7), round(d["lat"], 7)]},
                properties={"tree_id": d["tree_id"], "severity": d["severity"],
                            "severity_label": H.SEVERITY.get(d["severity"], "unrated"),
                            "health_notes": d["health_notes"], "notes": d["notes"],
                            "observation_count": d["observation_count"], "last_seen_at": _iso(d["last_seen_at"]),
                            "first_seen_at": _iso(d["created_at"]),
                            "severity_history": [{"timestamp": _iso(h["timestamp"]), "severity": h["severity"]}
                                                 for h in d["severity_history"]],
                            "thumbnail_url": _image_url(thumb),
                            "main_condition": d["main_condition"],
                            "main_condition_name": D.CONDITIONS[d["main_condition"]]["name"]
                            if d["main_condition"] else None,
                            "stress_score": A.stress_score(d),
                            "latest_sensors": d["latest_sensors"]}))
        return S.ForestMap(forest=forest_summary(ws.forest) if ws.forest else None, severity_scale=H.SEVERITY,
                           features=feats, trees_without_location=missing)

    # ------------------------------------------------------------------- meta
    @app.get(f"{PREFIX}/health", response_model=S.Health, tags=["meta"])
    def health():
        """Liveness check (no sign-in needed)."""
        return S.Health(status="ok", demo=demo, model_version=version,
                        face_blur=blur_enabled and privacy._get_detector() is not False, models=list(models))

    def model_choice(k: str) -> S.ModelChoice:
        m = models[k]
        return S.ModelChoice(key=k, name=m.name, tagline=m.text.get("tagline", ""),
                             description=m.text.get("description", ""), version=m.version,
                             checks_species=m.checks_species, embedding_dim=m.runtime.embedding_dim,
                             image_size=m.runtime.input_size, real_photo_top1=None if m.demo else m.text.get("real_photo_top1"),
                             speed=m.text.get("speed"), default=k == default_model, demo=m.demo)

    @app.get(f"{PREFIX}/models", response_model=S.ModelList, tags=["meta"])
    def list_models():
        """The re-ID models the app can choose between before a scan (no sign-in needed)."""
        return S.ModelList(default=default_model, models=[model_choice(k) for k in models])

    @api.get("/model", response_model=S.ModelInfo, tags=["meta"])
    def model_info(model: str | None = Query(None, description="delta (default) or gamma")):
        m = models[check_model(model)]
        rt, c = m.runtime, m.cal
        return S.ModelInfo(
            version=m.version, demo=demo, on_device=model_files if m.key == default_model else None,
            backbone=getattr(rt, "backbone", None), embedding_dim=rt.embedding_dim, image_size=rt.input_size,
            species_labels=list(rt.species_labels), reid_supported_species=sorted(REID_SUPPORTED),
            calibration=S.CalibrationInfo(target_false_match_rate=getattr(c, "target_fmr", None),
                                          species_threshold=c.species_threshold,
                                          match_threshold=c.match_threshold, provenance=c.provenance or {}))

    @api.get("/model/files/{name}", tags=["on-device"], response_class=FileResponse,
             responses={200: {"content": {"application/octet-stream": {}}}})
    def model_file(name: str):
        """Download the production model (hemlock.onnx, 87 MB) or its metadata (hemlock.json) to run it on
        the phone. Cache it: the ETag changes only with a new model version."""
        if model_files is None:
            raise ApiError(404, "no_model_files", "the server runs the demo (mock) model")
        files = {"hemlock.onnx": model_path, "hemlock.json": model_path.with_suffix(".json")}
        if name not in files:
            raise ApiError(404, "not_found", "available: hemlock.onnx, hemlock.json")
        return FileResponse(files[name], headers={"ETag": f'"{model_files.onnx_sha256[:16]}"',
                                                  "Cache-Control": "public, max-age=86400"})

    @api.get("/model/calibration", tags=["on-device"])
    def model_calibration():
        """The calibrated decision thresholds, same JSON as models/production/calibration.json."""
        return asdict(cal)

    @api.get("/protocol", response_model=S.Protocol, tags=["meta"])
    def protocol():
        """The guided photo sequence the app should walk the user through."""
        return S.Protocol(views=[_spec(v) for v in GUIDED_VIEWS], extra_trunk_views=[_spec(v) for v in EXTRA_TRUNK_VIEWS],
                          min_views=MIN_VIEWS, max_views=MAX_VIEWS, max_total_views=MAX_TOTAL_VIEWS,
                          max_image_bytes=MAX_IMAGE_BYTES)

    # ------------------------------------------------------- accounts/forests
    if accounts is not None:
        @api.post("/auth/register", response_model=S.LoginResult, status_code=201, tags=["account"])
        def register(body: S.RegisterRequest):
            try:
                accounts.register(body.email, body.password, body.name)
            except ValueError as e:
                raise ApiError(409, "email_taken", str(e)) from e
            return login(S.LoginRequest(email=body.email, password=body.password))

        @api.post("/auth/login", response_model=S.LoginResult, tags=["account"])
        def login(body: S.LoginRequest):
            res = accounts.login(body.email, body.password)
            if res is None:
                raise ApiError(401, "bad_credentials", "wrong email or password")
            token, u = res
            return S.LoginResult(token=token, user=S.UserOut(**asdict(u)))

        @api.post("/auth/logout", status_code=204, tags=["account"])
        def logout(request: Request, _user: User = Depends(current_user)):
            accounts.logout(bearer(request))
            return Response(status_code=204)

        @api.get("/me", response_model=S.AccountOverview, tags=["account"])
        def me(user: User = Depends(current_user)):
            """Everything on this account: each forest with tree counts and severity breakdown."""
            forests = [forest_summary(f) for f in accounts.forests(user.user_id)]
            totals = {"forests": len(forests), "trees": sum(f.tree_count for f in forests),
                      "observations": sum(f.observation_count for f in forests)}
            for f in forests:
                for k, v in f.severity_counts.items():
                    totals[k] = totals.get(k, 0) + v
            return S.AccountOverview(user=S.UserOut(**asdict(user)), forests=forests, totals=totals)

        @api.get("/forests", response_model=list[S.ForestSummary], tags=["account"])
        def list_forests(user: User = Depends(current_user)):
            return [forest_summary(f) for f in accounts.forests(user.user_id)]

        @api.post("/forests", response_model=S.ForestSummary, status_code=201, tags=["account"])
        def create_forest(body: S.ForestCreate, user: User = Depends(current_user)):
            try:
                return forest_summary(accounts.create_forest(user.user_id, body.name, body.lat, body.lon))
            except ValueError as e:
                raise ApiError(409, "forest_exists", str(e)) from e

        @api.get("/forests/{forest_id}", response_model=S.ForestSummary, tags=["account"])
        def get_forest_summary(forest_id: int, user: User = Depends(current_user)):
            return forest_summary(get_forest(user, forest_id))

        @api.delete("/forests/{forest_id}", status_code=204, tags=["account"])
        def delete_forest(forest_id: int, confirm_name: str = Query(..., description="the forest's exact name"),
                          user: User = Depends(current_user)):
            """Delete a forest with all its trees, visits, photos and sections. Cannot be undone, so the
            forest's exact name must be sent as `confirm_name`."""
            f = get_forest(user, forest_id)
            if confirm_name.strip() != f.name:
                raise ApiError(400, "name_mismatch", f"type the forest's name exactly to delete it: {f.name}")
            with db_lock:
                accounts.delete_forest(user.user_id, forest_id)
            return Response(status_code=204)

        def ws_for(user: User, forest_id: int) -> Workspace:
            f = get_forest(user, forest_id)
            return Workspace(accounts.pipeline(f), f"{user.user_id}:{f.forest_id}", user, f)

        @api.get("/forests/{forest_id}/analysis", tags=["analysis"])
        def forest_analysis(forest_id: int, west: float | None = None, south: float | None = None,
                            east: float | None = None, north: float | None = None,
                            cell_m: float = Query(150, ge=20, le=5000), user: User = Depends(current_user)):
            """Same as /analysis for a given forest (optionally an area inside it)."""
            return analysis_for(ws_for(user, forest_id), parse_bbox(west, south, east, north), cell_m)

        def assistant_tools(user: User) -> dict:
            def overview(_):
                out = []
                for f in accounts.forests(user.user_id):
                    summ = A.summarize(A.tree_profiles(accounts.pipeline(f).repo))
                    out.append({"forest_id": f.forest_id, "name": f.name, "trees": summ["trees"],
                                "severity_counts": summ["severity_counts"],
                                "most_prominent_condition": summ["most_prominent_condition"],
                                "pct_moderate_or_severe": summ["pct_moderate_or_severe"]})
                return out

            def forest(i):
                a = analysis_for(ws_for(user, int(i["forest_id"])))
                return {"forest": a["forest"], "summary": a["summary"], "worst_trees": a["worst_trees"]}

            def zones_tool(i):
                ws = ws_for(user, int(i["forest_id"]))
                return A.zones(A.tree_profiles(ws.repo), float(i.get("cell_m") or 150))[:15]

            def trees(i):
                ps = A.tree_profiles(ws_for(user, int(i["forest_id"])).repo)
                if i.get("condition"):
                    ps = [p for p in ps if i["condition"] in p["conditions"]
                          and p["conditions"][i["condition"]]["level"] in ("likely", "possible")]
                if i.get("min_severity") is not None:
                    ps = [p for p in ps if (p["severity"] or 0) >= int(i["min_severity"])]
                ps.sort(key=A.stress_score, reverse=True)
                return [{"tree_id": p["tree_id"], "severity": p["severity"], "main_condition": p["main_condition"],
                         "stress_score": A.stress_score(p), "lat": p["lat"], "lon": p["lon"],
                         "visits": p["visits"], "latest_sensors": p["latest_sensors"]}
                        for p in ps[: int(i.get("limit") or 25)]]

            def tree(i):
                ws = ws_for(user, int(i["forest_id"]))
                return tree_detail(str(i["tree_id"]), ws).model_dump(exclude={"thumbnail_url"})

            return {"get_account_overview": overview, "get_forest_analysis": forest, "get_forest_zones": zones_tool,
                    "list_trees": trees, "get_tree": tree, "get_health_guide": lambda _: D.guide()}

        @api.post("/assistant/chat", response_model=S.ChatReply, tags=["assistant"])
        def assistant_chat(body: S.ChatRequest, user: User = Depends(current_user)):
            """Ask the AI assistant (Claude Haiku) about your forests. Send conversation_id back to continue."""
            ctx = []
            if body.forest_id is not None:
                f = get_forest(user, body.forest_id)
                ctx.append(f"looking at forest {f.forest_id} ({f.name})")
            if body.tree_id:
                ctx.append(f"looking at tree {body.tree_id}")
            try:
                return assistant.chat(f"user:{user.user_id}", body.message, assistant_tools(user),
                                      body.conversation_id, "; ".join(ctx) or None)
            except NotConfigured as e:
                raise ApiError(503, "assistant_not_configured", str(e)) from e
            except API_ERRORS as e:
                raise ApiError(502, "assistant_unavailable", f"the AI service failed: {e}") from e

        @api.get("/forests/{forest_id}/map", response_model=S.ForestMap, tags=["map"])
        def get_forest_map(forest_id: int, user: User = Depends(current_user)):
            """Every tree of the forest as a GeoJSON point with its latest severity."""
            f = get_forest(user, forest_id)
            return forest_map(Workspace(accounts.pipeline(f), f"{user.user_id}:{f.forest_id}", user, f))

    def analysis_for(ws: Workspace, bbox: tuple | None = None, cell_m: float = 150.0) -> dict:
        all_profs = A.tree_profiles(ws.repo)
        profs = [p for p in all_profs if A.in_bbox(p, bbox)] if bbox else all_profs
        z = A.zones(profs, cell_m)
        return {"forest": forest_summary(ws.forest).model_dump() if ws.forest else None,
                "area": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]} if bbox else None,
                "summary": A.summarize(profs), "zones": z,
                "hotspots": A.hotspots(profs, cell_m),
                "trends": A.trends(ws.repo, {p["tree_id"] for p in profs}),
                "sections": [section_out(sec, all_profs) for sec in SEC.list_sections(ws.repo)] if not bbox else [],
                "worst_trees": [{"tree_id": p["tree_id"], "stress_score": A.stress_score(p), "severity": p["severity"],
                                 "main_condition": p["main_condition"], "lat": p["lat"], "lon": p["lon"]}
                                for p in sorted(profs, key=A.stress_score, reverse=True)[:10]]}

    def section_out(sec: dict, profs: list[dict]) -> dict:
        ps = [p for p in profs if A.in_bbox(p, tuple(sec["bbox"]))]
        summ = A.summarize(ps)
        return S.Section(section_id=sec["section_id"], name=sec["name"], bbox=sec["bbox"], trees=summ["trees"],
                         mean_severity=summ["mean_severity"], pct_moderate_or_severe=summ["pct_moderate_or_severe"],
                         most_prominent_condition=summ["most_prominent_condition"],
                         stress_score=round(sum(A.stress_score(p) for p in ps) / len(ps), 3) if ps else None,
                         condition_counts={c: v["likely"] + v["possible"] for c, v in summ["conditions"].items()}
                         ).model_dump()

    def parse_bbox(west, south, east, north):
        vals = (west, south, east, north)
        if all(v is None for v in vals):
            return None
        if any(v is None for v in vals) or west >= east or south >= north:
            raise ApiError(400, "bad_area", "give west<east and south<north (decimal degrees)")
        return vals

    @api.get("/analysis", tags=["analysis"])
    def current_analysis(west: float | None = None, south: float | None = None, east: float | None = None,
                         north: float | None = None, cell_m: float = Query(150, ge=20, le=5000),
                         ws: Workspace = WS):
        """Analysis of the current forest, or of the area west/south/east/north inside it: severity, condition
        prevalence, sensor averages, ranked zones (where trees suffer most), worst trees, recommendations."""
        return analysis_for(ws, parse_bbox(west, south, east, north), cell_m)

    @api.get("/landmarks", tags=["map"])
    def forest_landmarks(ws: Workspace = WS):
        """Streams, ridges, peaks, trails of the current forest as GeoJSON (approximate; demo forests only)."""
        return G.landmarks(ws.forest.name if ws.forest else "")

    @api.get("/sections", response_model=list[S.Section], tags=["analysis"])
    def list_sections(ws: Workspace = WS):
        """The forest's named sections with their health summary."""
        profs = A.tree_profiles(ws.repo)
        return [section_out(sec, profs) for sec in SEC.list_sections(ws.repo)]

    @api.post("/sections", response_model=S.Section, status_code=201, tags=["analysis"])
    def create_section(body: S.SectionCreate, ws: Workspace = WS):
        """Save an area of the map (e.g. the current view) as a named section."""
        bbox = parse_bbox(body.west, body.south, body.east, body.north)
        try:
            sec = SEC.create_section(ws.repo, body.name, bbox)
        except ValueError as e:
            raise ApiError(409, "section_exists", str(e)) from e
        return section_out(sec, A.tree_profiles(ws.repo))

    def find_section(ws: Workspace, section_id: int) -> dict:
        sec = SEC.get_section(ws.repo, section_id)
        if sec is None:
            raise ApiError(404, "section_not_found", f"no section {section_id} in this forest")
        return sec

    @api.get("/sections/{section_id}/analysis", tags=["analysis"])
    def section_analysis(section_id: int, cell_m: float = Query(150, ge=20, le=5000), ws: Workspace = WS):
        """Analysis of one section: severity, conditions, hotspots, trends, worst trees, recommendations."""
        sec = find_section(ws, section_id)
        return {**analysis_for(ws, tuple(sec["bbox"]), cell_m), "section": sec}

    @api.delete("/sections/{section_id}", status_code=204, tags=["analysis"])
    def delete_section(section_id: int, ws: Workspace = WS):
        find_section(ws, section_id)
        SEC.delete_section(ws.repo, section_id)
        return Response(status_code=204)

    @api.post("/species-check", response_model=S.SpeciesCheck, tags=["capture"])
    async def species_check(image: UploadFile = File(..., description="one photo of the bark"), ws: Workspace = WS):
        """Is this a hemlock? Runs the species model on one photo. Nothing is stored."""
        data, rgb = await read_image(image)
        sp_key = next((k for k, m in models.items() if m.checks_species), None)
        if sp_key is None:
            raise ApiError(409, "no_species_model", "no loaded model has a species check")
        vr = add_view(ws, [], data, rgb, GUIDED_VIEWS[0].key, None, sp_key)
        del rgb
        q = _view_quality(vr)
        th = float(pipe_for(ws, sp_key).cal.species_threshold)
        if vr.species_logits is None:
            raise ApiError(422, "unusable_photo", "photo rejected before the model: " + "; ".join(q.problems))
        p = softmax(vr.species_logits[None])[0]
        probs = {SPECIES[i]: float(p[i]) for i in range(len(SPECIES))}
        top = _species_scores(probs)
        hp = probs["tsuga_canadensis"]
        verdict = "hemlock" if top[0].label == "tsuga_canadensis" and hp >= th else \
            "not_hemlock" if hp < 0.2 else "unsure"
        msg = {"hemlock": f"Eastern hemlock ({hp:.0%} sure).",
               "not_hemlock": f"Not a hemlock. Closest match: {top[0].name} ({top[0].probability:.0%}).",
               "unsure": f"Not sure ({hp:.0%} hemlock). Take a sharper, closer photo of the bark; one photo is "
                         "less reliable than a full 3-photo scan."}[verdict]
        return S.SpeciesCheck(is_hemlock=verdict == "hemlock", verdict=verdict, hemlock_probability=round(hp, 4),
                              threshold=round(th, 4), species=top[0], top=top, quality=q, message=msg)

    def gallery_for(ws: Workspace) -> S.Gallery:
        import base64

        import numpy as np

        sp = sorted(REID_SUPPORTED)[0]
        with model_ready(ws, ws.model) as p:
            tids, oids, emb = ws.repo.gallery(sp, p.model_key)
        out = []
        for t, o, e in zip(tids, oids, emb):
            v = np.asarray(e, dtype=np.float32)
            v = v / max(float(np.linalg.norm(v)), 1e-12)
            out.append(S.GalleryObservation(tree_id=t, observation_id=o,
                                            embedding_b64=base64.b64encode(v.astype("<f4").tobytes()).decode()))
        return S.Gallery(model_version=models[ws.model].version, embedding_dim=models[ws.model].runtime.embedding_dim,
                         species=sp,
                         tree_ids=sorted(set(tids)), observations=out)

    @api.get("/gallery", response_model=S.Gallery, tags=["on-device"])
    def current_gallery(ws: Workspace = WS):
        """Fingerprints of every tree in the current forest, so the phone can identify trees offline. Photos
        taken offline are queued and sent to POST /identify when back online (the server decides finally)."""
        return gallery_for(ws)

    @api.get("/map", response_model=S.ForestMap, tags=["map"])
    def current_map(ws: Workspace = WS):
        """Map of the current forest (X-Forest-Id) or of the single database."""
        return forest_map(ws)

    # --------------------------------------------------------- guided capture
    @api.post("/captures", response_model=S.CaptureCreated, status_code=201, tags=["capture"])
    def create_capture(body: S.CaptureCreate | None = None, ws: Workspace = WS):
        """Start a guided capture with one re-ID model (body {"model": "gamma"}, else X-Model, else delta).
        Photos are held in memory for 30 min until identify."""
        key = check_model(body.model) if body and body.model else ws.model
        cid = sessions.new()
        s = sessions.get(cid)
        s["owner"], s["model"] = ws.key, key
        return S.CaptureCreated(capture_id=cid, model=key, model_name=models[key].name,
                                next_view=_spec(GUIDED_VIEWS[0]), expires_in_s=SESSION_TTL_S)

    @api.get("/captures/{capture_id}", response_model=S.CaptureState, tags=["capture"])
    def capture_state(capture_id: str, ws: Workspace = WS):
        s = get_capture(capture_id, ws)
        views = s["views"]
        n_id = sum(1 for v in views if spec_for(v.view_type).identity_view)
        return S.CaptureState(capture_id=capture_id, views=[_view_quality(v) for v in views],
                              accepted_views=len(views), can_identify=n_id >= MIN_VIEWS,
                              next_view=_spec(s.get("next", GUIDED_VIEWS[0])), result=s.get("result_out"))

    @api.post("/captures/{capture_id}/views", response_model=S.ViewAdded, tags=["capture"])
    async def capture_view(capture_id: str, image: UploadFile = File(..., description="JPEG or PNG"),
                           view_key: str | None = Form(None, description="default: the view the server asked for"),
                           heading_deg: float | None = Form(None, ge=0, lt=360, description="compass heading"),
                           ws: Workspace = WS):
        """Add one photo. Rejected photos (blurry, dark, duplicate...) are reported and must be retaken."""
        s = get_capture(capture_id, ws)
        if s.get("result_out") is not None:
            raise ApiError(409, "capture_finished", "this capture was already identified; start a new one")
        data, rgb = await read_image(image)
        views: list[ViewResult] = s["views"]
        if view_key is None:
            nxt = s.get("next") or next_view({v.view_type for v in views})
            if nxt is None:
                raise ApiError(400, "capture_complete", "all views captured; call identify")
            view_key = nxt.key
        check_view_key(view_key)
        if len(views) >= MAX_TOTAL_VIEWS:
            raise ApiError(400, "too_many_views", f"at most {MAX_TOTAL_VIEWS} views")
        vr = add_view(ws, views, data, rgb, view_key, heading_deg, s.get("model"))
        del rgb
        if vr.accepted:
            s["views"] = [v for v in views if v.view_type != view_key] + [vr]
            s["next"] = next_view({v.view_type for v in s["views"]}, need_identity=s.get("need_identity", False))
        else:
            s["next"] = spec_for(view_key)
        n_std = sum(1 for v in s["views"] if v.view_type in {g.key for g in GUIDED_VIEWS})
        n_id = sum(1 for v in s["views"] if spec_for(v.view_type).identity_view)
        return S.ViewAdded(view=_view_quality(vr), accepted_views=len(s["views"]),
                           progress=round(min(1.0, n_std / MAX_VIEWS), 3), can_identify=n_id >= MIN_VIEWS,
                           next_view=_spec(s["next"]))

    @api.post("/captures/{capture_id}/identify", response_model=S.IdentifyResult, tags=["capture"])
    def capture_identify(capture_id: str, body: S.IdentifyRequest | None = None, ws: Workspace = WS):
        """Decide existing / new / uncertain. If uncertain and another trunk view is available, nothing is
        stored and `action` is `capture_another_view`; otherwise the observation is stored."""
        body = body or S.IdentifyRequest()
        s = get_capture(capture_id, ws)
        if s.get("result_out") is not None:
            return s["result_out"]
        views = s["views"]
        key = s.get("model") or ws.model
        with model_ready(ws, key) as pipe, db_lock:
            r = pipe.identify(views, commit=False)
            if r.status == "recapture":
                return model_result(_result(r, "retake", views, s.get("next")), key, pipe)
            if r.status == "uncertain" and not body.force_commit:
                s["need_identity"] = True
                nxt = next_view({v.view_type for v in views}, need_identity=True)
                if nxt is not None:
                    s["next"] = nxt
                    return model_result(_result(r, "capture_another_view", views, nxt), key, pipe)
            r = pipe.commit(views, r, fix=_fix(body.location))
            guessed = body.accept_best_guess and accept_best_guess_fn(ws, r)
            findings = record_visit(ws, r.observation_id, body.severity, body.health_notes,
                                    F.clean_sensors(body.sensors.model_dump()) if body.sensors else None,
                                    body.signs)
        out = model_result(_result(r, "done" if guessed or r.status in ("existing", "new", "rejected_species",
                                                                          "unsupported_species") else "review",
                                   views), key, pipe)
        out.findings = findings
        if accounts is not None and ws.forest is not None and r.observation_id:
            accounts.after_commit(ws.forest, key)
        s["result_out"] = out
        s["views"] = [ViewResult(v.index, v.view_type, v.quality, faces_blurred=v.faces_blurred) for v in views]
        return out

    @api.delete("/captures/{capture_id}", status_code=204, tags=["capture"])
    def cancel_capture(capture_id: str, ws: Workspace = WS):
        get_capture(capture_id, ws)
        sessions.drop(capture_id)
        return Response(status_code=204)

    # --------------------------------------------------------------- one-shot
    @api.post("/identify", response_model=S.IdentifyResult, tags=["capture"])
    async def identify_oneshot(
        images: list[UploadFile] = File(..., description=f"{MIN_VIEWS}-{MAX_TOTAL_VIEWS} photos in protocol order"),
        view_keys: str | None = Form(None, description="comma-separated view keys, one per image "
                                                       "(default: trunk_north, trunk_right, trunk_right2, ...)"),
        headings: str | None = Form(None, description="comma-separated compass headings, one per image"),
        lat: float | None = Form(None, ge=-90, le=90), lon: float | None = Form(None, ge=-180, le=180),
        accuracy_m: float | None = Form(None, ge=0),
        severity: int | None = Form(None, ge=0, le=3, description=S.SEVERITY_DOC),
        health_notes: str | None = Form(None, max_length=2000),
        soil_moisture_pct: float | None = Form(None), air_temp_c: float | None = Form(None),
        humidity_pct: float | None = Form(None), light_lux: float | None = Form(None),
        signs: str | None = Form(None, description="comma-separated " + S.SIGNS_DOC),
        accept_best_guess: bool = Form(False, description="if uncertain, assign the top candidate"),
        commit: bool = Form(True, description="false = dry run, nothing stored"),
        model: str | None = Form(None, description="re-ID model: delta (default) or gamma"),
        ws: Workspace = WS):
        """All photos in one request. Always stores the result (uncertain ones for review) unless commit=false."""
        if not MIN_VIEWS <= len(images) <= MAX_TOTAL_VIEWS:
            raise ApiError(400, "wrong_view_count", f"send {MIN_VIEWS}-{MAX_TOTAL_VIEWS} images, got {len(images)}")
        default = [v.key for v in GUIDED_VIEWS[:MIN_VIEWS] + EXTRA_TRUNK_VIEWS + GUIDED_VIEWS[MIN_VIEWS:]]
        keys = [k.strip() for k in view_keys.split(",")] if view_keys else default[: len(images)]
        heads = [float(h) if h.strip() else None for h in headings.split(",")] if headings else [None] * len(images)
        if len(keys) != len(images) or len(heads) != len(images):
            raise ApiError(400, "length_mismatch", "view_keys/headings need one entry per image")
        if len(set(keys)) != len(keys):
            raise ApiError(400, "duplicate_view_key", "each view_key may appear once")
        for k in keys:
            check_view_key(k)
        if (lat is None) != (lon is None):
            raise ApiError(400, "bad_location", "send both lat and lon")
        sensors = _form_sensors(soil_moisture_pct=soil_moisture_pct, air_temp_c=air_temp_c,
                                humidity_pct=humidity_pct, light_lux=light_lux)
        sign_list = _check_signs([x.strip() for x in signs.split(",") if x.strip()] if signs else [])
        key = check_model(model) if model else ws.model
        views: list[ViewResult] = []
        for img, k, h in zip(images, keys, heads):
            data, rgb = await read_image(img)
            vr = add_view(ws, views, data, rgb, k, h, key)
            del rgb
            views.append(vr)
        accepted = [v for v in views if v.accepted]
        loc = _location(lat, lon, accuracy_m)
        with model_ready(ws, key) as pipe, db_lock:
            r = pipe.identify(accepted, commit=False)
            if r.status == "recapture":
                return model_result(_result(r, "retake", views), key, pipe)
            guessed, findings = False, []
            if commit:
                r = pipe.commit(accepted, r, fix=_fix(loc))
                guessed = accept_best_guess and accept_best_guess_fn(ws, r)
                findings = record_visit(ws, r.observation_id, severity, health_notes, sensors, sign_list)
        out = model_result(_result(r, "review" if r.status == "uncertain" and not guessed else "done", views), key, pipe)
        out.findings = findings
        if commit and accounts is not None and ws.forest is not None and r.observation_id:
            accounts.after_commit(ws.forest, key)
        return out

    # -------------------------------------------------------------- database
    @api.get("/trees", response_model=S.TreePage, tags=["trees"])
    def list_trees(species: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                   ws: Workspace = WS):
        trees = sorted(ws.repo.list_trees(species), key=lambda t: t.last_seen_at, reverse=True)
        status = {d["tree_id"]: d for d in A.tree_profiles(ws.repo)}
        return S.TreePage(items=[tree_summary(ws, t, status.get(t.tree_id, {})) for t in trees[offset: offset + limit]],
                          total=len(trees), limit=limit, offset=offset)

    @api.get("/trees/{tree_id}", response_model=S.TreeDetail, tags=["trees"])
    def tree_detail(tree_id: str, ws: Workspace = WS):
        """A tree and its full observation history (oldest first), with severity per visit."""
        t = get_tree(ws, tree_id)
        obs = ws.repo.get_observations(tree_id)
        thumb = next((v.image_key for o in obs for v in o.views if v.image_key), None)
        prof = next((d for d in A.tree_profiles(ws.repo) if d["tree_id"] == tree_id), {})
        cur = sorted(prof.get("conditions", {}).values(), key=lambda f: -f["likelihood"])
        return S.TreeDetail(**tree_summary(ws, t, prof, thumb).model_dump(), observations=_observations(ws.repo, obs),
                            current_conditions=[_finding(f) for f in cur], latest_sensors=prof.get("latest_sensors"))

    @api.patch("/trees/{tree_id}", response_model=S.TreeSummary, tags=["trees"])
    def update_tree(tree_id: str, body: S.TreeUpdate, ws: Workspace = WS):
        get_tree(ws, tree_id)
        ws.repo.set_notes(tree_id, body.notes)
        return tree_summary(ws, ws.repo.get_tree(tree_id))

    @api.delete("/trees/{tree_id}", status_code=204, tags=["trees"])
    def delete_tree(tree_id: str, ws: Workspace = WS):
        """Delete a tree with all its visits, health records, sensor readings and photos (cannot be undone)."""
        t = get_tree(ws, tree_id)
        with db_lock:
            gone = ws.repo.delete_tree(t.tree_id, ("tree_health", "visit_sensors", "visit_signs", "visit_findings",
                                                   "visit_ai_inspection"))
            ws.invalidate(t.species)
        for k in gone:
            try:
                Path(ws.pipe.storage.path(k)).unlink(missing_ok=True)
            except (OSError, AttributeError):
                pass
        return Response(status_code=204)

    @api.post("/trees/{tree_id}/merge", response_model=S.TreeDetail, tags=["trees"])
    def merge_trees(tree_id: str, body: S.MergeRequest, ws: Workspace = WS):
        """Fix a duplicate: all observations of `duplicate_tree_id` move to this tree."""
        keep, drop = get_tree(ws, tree_id), get_tree(ws, body.duplicate_tree_id)
        if keep.tree_id == drop.tree_id:
            raise ApiError(400, "same_tree", "cannot merge a tree into itself")
        if keep.species != drop.species:
            raise ApiError(400, "species_mismatch", "trees have different species")
        with db_lock:
            ws.repo.merge_trees(keep.tree_id, drop.tree_id)
            ws.invalidate(keep.species)
        return tree_detail(tree_id, ws)

    @api.get("/observations", response_model=S.ObservationPage, tags=["observations"])
    def list_observations(status: list[str] | None = Query(None, description="e.g. status=uncertain"),
                          unassigned: bool = False, limit: int = Query(50, ge=1, le=500),
                          offset: int = Query(0, ge=0), ws: Workspace = WS):
        """Newest first. `?status=uncertain&unassigned=true` is the review queue."""
        items, total = ws.repo.list_observations(status, unassigned, limit, offset)
        return S.ObservationPage(items=_observations(ws.repo, items), total=total, limit=limit, offset=offset)

    def find_observation(ws: Workspace, observation_id: str) -> ObservationRecord:
        o = ws.repo.get_observation(observation_id)
        if o is None:
            raise ApiError(404, "observation_not_found", f"unknown observation {observation_id}")
        return o

    @api.get("/observations/{observation_id}", response_model=S.Observation, tags=["observations"])
    def get_observation(observation_id: str, ws: Workspace = WS):
        return _observations(ws.repo, [find_observation(ws, observation_id)])[0]

    @api.put("/observations/{observation_id}/health", response_model=S.Observation, tags=["observations"])
    def set_observation_health(observation_id: str, body: S.HealthUpdate, ws: Workspace = WS):
        """Record or change the severity rating of a visit."""
        find_observation(ws, observation_id)
        H.set_health(ws.repo, observation_id, body.severity, body.notes)
        refresh_findings(ws, observation_id)
        return get_observation(observation_id, ws)

    @api.put("/observations/{observation_id}/signs", response_model=S.Observation, tags=["health"])
    def set_observation_signs(observation_id: str, body: S.SignsUpdate, ws: Workspace = WS):
        """Record the signs the observer checked on this visit (replaces the list); findings are recomputed."""
        find_observation(ws, observation_id)
        F.set_signs(ws.repo, observation_id, _check_signs(body.signs))
        refresh_findings(ws, observation_id)
        return get_observation(observation_id, ws)

    @api.put("/observations/{observation_id}/sensors", response_model=S.Observation, tags=["health"])
    def set_observation_sensors(observation_id: str, body: S.Sensors, ws: Workspace = WS):
        """Attach ESP32 sensor readings to an existing visit."""
        find_observation(ws, observation_id)
        sensors = F.clean_sensors(body.model_dump())
        if not sensors:
            raise ApiError(400, "no_readings", "send at least one reading")
        F.set_sensors(ws.repo, observation_id, sensors)
        refresh_findings(ws, observation_id)
        return get_observation(observation_id, ws)

    @api.post("/observations/{observation_id}/inspect", response_model=S.Observation, tags=["health"])
    def inspect_observation(observation_id: str, ws: Workspace = WS):
        """AI photo check (Claude Haiku) of this visit's twig-underside close-ups for adelgid wool and scales.
        Suggestions are stored separately from observer signs and count as weaker evidence."""
        o = find_observation(ws, observation_id)
        keys = [v.image_key for v in o.views if v.image_key and v.view_type == "twig_underside"]
        if not keys:
            raise ApiError(400, "no_twig_photos", "this visit has no twig_underside photo; trunk photos cannot "
                                                  "show HWA or EHS")
        try:
            res = assistant.inspect_photos([ws.pipe.storage.get(k) for k in keys])
        except NotConfigured as e:
            raise ApiError(503, "assistant_not_configured", str(e)) from e
        except API_ERRORS as e:
            raise ApiError(502, "assistant_unavailable", f"the AI service failed: {e}") from e
        F.set_ai_inspection(ws.repo, observation_id, res)
        refresh_findings(ws, observation_id)
        return get_observation(observation_id, ws)

    @api.post("/trees/{tree_id}/visits", response_model=S.Observation, status_code=201, tags=["health"])
    def add_visit(tree_id: str, body: S.VisitCreate, ws: Workspace = WS):
        """A visit without photos: ESP32 sensor readings and/or observer signs and severity at a known tree."""
        t = get_tree(ws, tree_id)
        sensors = F.clean_sensors(body.sensors.model_dump()) if body.sensors else None
        if not (sensors or body.signs or body.severity is not None or body.health_notes):
            raise ApiError(400, "empty_visit", "send sensors, signs, severity or notes")
        import uuid as _uuid
        loc = body.location
        oid = ws.repo.add_observation(ObservationRecord(
            _uuid.uuid4().hex, t.tree_id, time.time(), "field_visit", t.species, None, None, None,
            loc.lat if loc else None, loc.lon if loc else None, loc.accuracy_m if loc else None, None, {},
            {"kind": "sensor_or_observer_only"}))
        record_visit(ws, oid, body.severity, body.health_notes, sensors, body.signs)
        return get_observation(oid, ws)

    @app.get(f"{PREFIX}/health-guide", tags=["health"])
    def health_guide():
        """Conditions, signs checklist, severity scale, sensor thresholds and general advice (no sign-in)."""
        return D.guide()

    @api.post("/observations/{observation_id}/assign", response_model=S.AssignResult, tags=["observations"])
    def assign_observation(observation_id: str, body: S.AssignRequest, ws: Workspace = WS):
        """The user decides which tree an observation belongs to: resolve an uncertain one, or correct a
        wrong automatic decision (one tap on a candidate). `"new"` registers a new tree. A tree left with
        no observations is retired, never reused."""
        repo = ws.repo
        with db_lock:
            o = find_observation(ws, observation_id)
            if o.species not in REID_SUPPORTED or o.aggregated_embedding is None:
                raise ApiError(400, "not_assignable", "only identity observations of supported species can be "
                                                      "assigned")
            created = body.tree_id == "new"
            if created:
                tid = repo.create_tree(o.species, ID_PREFIX.get(o.species, "T"))
            else:
                t = get_tree(ws, body.tree_id)
                if t.species != o.species:
                    raise ApiError(400, "species_mismatch", f"{t.tree_id} is {t.species}, observation is {o.species}")
                tid = t.tree_id
            if o.tree_id is None:
                repo.assign_observation(observation_id, tid, "user_confirmed")
            elif o.tree_id != tid:
                repo.reassign_observation(observation_id, tid)
            ws.invalidate(o.species)
        return S.AssignResult(observation_id=observation_id, tree_id=tid, created_tree=created)

    @api.get("/images/{key}", tags=["observations"], response_class=Response,
             responses={200: {"content": {"image/jpeg": {}}}})
    def image(key: str, ws: Workspace = WS):
        if not key.replace(".", "").isalnum() or len(key) > 80:
            raise ApiError(400, "bad_key", "bad image key")
        try:
            data = ws.pipe.storage.get(key)
        except FileNotFoundError as e:
            raise ApiError(404, "image_not_found", "image not found") from e
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000"})

    app.include_router(api)

    @app.get("/map", include_in_schema=False)
    def map_page():
        return FileResponse(STATIC / "map.html")

    @app.get("/app", include_in_schema=False)
    def app_page():
        return FileResponse(STATIC / "app.html")

    @app.get("/ort/{name}", include_in_schema=False)
    def ort_file(name: str):
        """onnxruntime-web (MIT), vendored by `npm run build:web`, so the phone needs no CDN."""
        types = {"ort.wasm.min.js": "text/javascript", "ort-wasm-simd-threaded.mjs": "text/javascript",
                 "ort-wasm-simd-threaded.wasm": "application/wasm"}
        if name not in types:
            raise ApiError(404, "not_found", "unknown file")
        return FileResponse(STATIC / "ort" / name, media_type=types[name],
                            headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/ondevice.js", include_in_schema=False)
    def ondevice_js():
        """The on-device engine (built from client/src/ondevice.ts by `npm run build:web`)."""
        return FileResponse(STATIC / "ondevice.js", media_type="text/javascript")

    @app.get("/", include_in_schema=False)
    def root():
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/app" if accounts is not None else "/docs")

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Hemlock Sentinel mobile API")
    ap.add_argument("--data", default=os.environ.get("HEMLOCK_DATA", "runs/api"),
                    help="accounts mode: where accounts and per-forest databases live")
    ap.add_argument("--single", action="store_true", help="one shared database, no sign-in")
    ap.add_argument("--no-demo-account", action="store_true", help="do not create the demo account")
    ap.add_argument("--db", default=os.environ.get("HEMLOCK_DB", "runs/api/trees.sqlite"), help="--single only")
    ap.add_argument("--blobs", default=os.environ.get("HEMLOCK_BLOBS", "runs/api/blobs"), help="--single only")
    ap.add_argument("--model", default=os.environ.get("HEMLOCK_MODEL", str(DELTA_MODEL)), help="model delta (ONNX)")
    ap.add_argument("--calibration", default=os.environ.get("HEMLOCK_CALIBRATION", str(DELTA_CALIBRATION)))
    ap.add_argument("--gamma-model", default=os.environ.get("HEMLOCK_GAMMA_MODEL", str(GAMMA_MODEL)),
                    help="model gamma (ONNX); skipped if the file is missing")
    ap.add_argument("--gamma-calibration", default=os.environ.get("HEMLOCK_GAMMA_CALIBRATION", str(GAMMA_CALIBRATION)))
    ap.add_argument("--no-gamma", action="store_true", help="run model delta only")
    ap.add_argument("--demo", action="store_true", help="mock model (no weights); results are meaningless")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--cors", default=os.environ.get("HEMLOCK_CORS", "*"), help="comma-separated origins")
    args = ap.parse_args()
    if not args.demo and not Path(args.model).exists():
        raise SystemExit(f"model not found: {args.model}\n"
                         "Run from the repository root (the folder containing models/production/), or pass "
                         "--model path/to/hemlock.onnx --calibration path/to/calibration.json, "
                         "or use --demo to run without the model.")
    import uvicorn

    model = None if args.demo else args.model
    key = os.environ.get("HEMLOCK_API_KEY") or None
    if args.single:
        pipe, demo = build_pipeline(args.db, args.blobs, model, args.calibration)
        runtime = pipe.runtime
        app = create_api(pipe, demo, key, args.cors.split(","))
        mode = "single database, no sign-in"
    else:
        from .demo_seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo

        reg = load_models(model, args.calibration, None if args.no_gamma else args.gamma_model, args.gamma_calibration)
        demo = model is None
        accounts = Accounts(args.data, models=reg)
        runtime = accounts.runtime
        if not args.no_demo_account:
            seed_demo(accounts)
            mode = f"accounts (demo sign-in: {DEMO_EMAIL} / {DEMO_PASSWORD})"
        else:
            mode = "accounts"
        app = create_api(demo=demo, api_key=key, cors_origins=args.cors.split(","), accounts=accounts)
    names = ", ".join(f"{k}={m.version}" for k, m in (accounts.models.items() if not args.single else {}.items()))
    print(f"Hemlock Sentinel API: model={'DEMO (mock)' if demo else runtime.version}, mode={mode}\n"
          f"  re-ID models: {names or 'delta only (--single)'}\n"
          f"  docs: http://localhost:{args.port}/docs   map: http://localhost:{args.port}/map")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
