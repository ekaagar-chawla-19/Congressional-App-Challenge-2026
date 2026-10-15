"""Hemlock Sentinel mobile API (v1): the backend a React Native / Expo app talks to.

The phone takes the photos; this server runs the trained model (ONNX), decides
existing / new / uncertain tree, and keeps the tree database. Interactive docs
are served at /docs (try every endpoint from the browser) and the machine-readable
contract at /openapi.json.

Run:  hemlock-api                       # production model in models/production/
      hemlock-api --demo                # mock model, no weights needed
      HEMLOCK_API_KEY=secret hemlock-api  # require header X-API-Key on /api/v1/*

Two ways to identify a tree:
* guided:   POST /captures -> POST /captures/{id}/views (one photo at a time, instant
            quality feedback) -> POST /captures/{id}/identify
* one-shot: POST /identify with all 3-7 photos in one multipart request.
Uncertain results are stored unassigned; resolve them with POST /observations/{id}/assign.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hmac
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
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
from ..species.labels import COMMON_NAMES, ID_PREFIX, REID_SUPPORTED
from . import schemas as S

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = ROOT / "models/production/hemlock.onnx"
DEFAULT_CALIBRATION = ROOT / "models/production/calibration.json"
MAX_IMAGE_BYTES = 25_000_000
PREFIX = "/api/v1"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _image_url(key: str | None) -> str | None:
    return f"{PREFIX}/images/{key}" if key else None


def _spec(v: ViewSpec | None) -> S.ViewSpecOut | None:
    return S.ViewSpecOut(**asdict(v)) if v else None


def _view_quality(v: ViewResult) -> S.ViewQuality:
    return S.ViewQuality(index=v.index, view_type=v.view_type, accepted=v.accepted, problems=v.quality.problems,
                         warnings=v.quality.warnings,
                         metrics={k: round(float(x), 4) for k, x in v.quality.metrics.items()},
                         faces_blurred=v.faces_blurred)


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
    if r.species:
        out.species = S.Species(label=r.species.species, name=r.species.common_name,
                                confidence=round(r.species.confidence, 4))
    if r.decision:
        out.probability = round(r.decision.probability, 4)
        out.candidates = _candidates(r.decision.candidates)
        c = r.decision.consistency
        if c:
            out.consistency = S.Consistency(per_view_top=list(c.per_view_top), agreement=round(c.agreement, 3),
                                            contradicting_views=[i + 1 for i in c.contradicting_views])
    return out


def _observation(o: ObservationRecord) -> S.Observation:
    loc = S.Location(lat=o.lat, lon=o.lon, accuracy_m=o.gps_accuracy_m) if o.lat is not None else None
    return S.Observation(
        observation_id=o.observation_id, tree_id=o.tree_id, timestamp=_iso(o.timestamp), status=o.decision,
        species=o.species, species_confidence=o.species_confidence, match_probability=o.match_probability,
        location=loc, model_version=o.model_version, candidates=_candidates(o.metadata.get("candidates", [])),
        views=[S.ViewOut(view_index=v.view_index, view_type=v.view_type, image_url=_image_url(v.image_key),
                         heading_deg=v.heading_deg) for v in o.views])


def _fix(loc: S.Location | None) -> GeoFix | None:
    return GeoFix(loc.lat, loc.lon, loc.accuracy_m if loc.accuracy_m is not None else float("nan")) if loc else None


def create_api(pipeline: HemlockSentinel, demo: bool = False, api_key: str | None = None,
               cors_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="Hemlock Sentinel API", version="1.0.0",
                  description=__doc__.split("Run:")[0].strip() + "\n\nUncertain results are stored unassigned; "
                  "resolve them with `POST /api/v1/observations/{id}/assign`.")
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins or ["*"], allow_methods=["*"],
                       allow_headers=["*"])
    sessions = Sessions()
    # Retrieval index, ID allocation and corrections share in-memory state; the model
    # forward pass (the slow part, in add_view) runs outside this lock.
    db_lock = threading.Lock()
    repo = pipeline.repo
    version = getattr(pipeline.runtime, "version", "unknown")

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

    errors = {r: {"model": S.ErrorResponse} for r in (400, 401, 404, 409, 413, 422)}
    api = APIRouter(prefix=PREFIX, dependencies=[Depends(require_key)], responses=errors)

    # ----------------------------------------------------------------- shared
    def get_capture(cid: str) -> dict:
        try:
            return sessions.get(cid)
        except StarletteHTTPException as e:
            raise ApiError(404, "capture_not_found", "capture not found or expired (30 min)") from e

    def get_tree(tree_id: str) -> TreeRecord:
        t = repo.get_tree(tree_id)
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

    def add_view(views: list[ViewResult], data: bytes, rgb, view_key: str, heading: float | None) -> ViewResult:
        prev = [v for v in views if v.view_type != view_key]
        return pipeline.process_view(Frame(rgb, time.time(), encoded=data, heading_deg=heading), len(prev), prev,
                                     view_key=view_key)

    def check_view_key(key: str) -> None:
        try:
            spec_for(key)
        except KeyError as e:
            raise ApiError(400, "unknown_view", f"unknown view_key {key!r}; see GET {PREFIX}/protocol") from e

    def tree_summary(t: TreeRecord, thumb: str | None = None) -> S.TreeSummary:
        if thumb is None:
            views = repo.gallery_views(t.tree_id)
            thumb = next((v.image_key for v in views if v.image_key), None)
        return S.TreeSummary(tree_id=t.tree_id, species=t.species, name=COMMON_NAMES.get(t.species, t.species),
                             created_at=_iso(t.created_at), last_seen_at=_iso(t.last_seen_at),
                             observation_count=t.observation_count, notes=t.notes, thumbnail_url=_image_url(thumb))

    # ------------------------------------------------------------------- meta
    @app.get(f"{PREFIX}/health", response_model=S.Health, tags=["meta"])
    def health():
        """Liveness check (no API key needed)."""
        return S.Health(status="ok", demo=demo, model_version=version,
                        face_blur=pipeline.cfg.blur_faces and privacy._get_detector() is not False)

    @api.get("/model", response_model=S.ModelInfo, tags=["meta"])
    def model_info():
        cal = pipeline.cal
        return S.ModelInfo(
            version=version, demo=demo, backbone=getattr(pipeline.runtime, "backbone", None),
            embedding_dim=pipeline.runtime.embedding_dim, image_size=pipeline.runtime.input_size,
            species_labels=list(pipeline.runtime.species_labels), reid_supported_species=sorted(REID_SUPPORTED),
            calibration=S.CalibrationInfo(target_false_match_rate=getattr(cal, "target_fmr", None),
                                          species_threshold=cal.species_threshold,
                                          match_threshold=cal.match_threshold, provenance=cal.provenance or {}))

    @api.get("/protocol", response_model=S.Protocol, tags=["meta"])
    def protocol():
        """The guided photo sequence the app should walk the user through."""
        return S.Protocol(views=[_spec(v) for v in GUIDED_VIEWS], extra_trunk_views=[_spec(v) for v in EXTRA_TRUNK_VIEWS],
                          min_views=MIN_VIEWS, max_views=MAX_VIEWS, max_total_views=MAX_TOTAL_VIEWS,
                          max_image_bytes=MAX_IMAGE_BYTES)

    # --------------------------------------------------------- guided capture
    @api.post("/captures", response_model=S.CaptureCreated, status_code=201, tags=["capture"])
    def create_capture():
        """Start a guided capture. Photos are held in memory for 30 min until identify."""
        return S.CaptureCreated(capture_id=sessions.new(), next_view=_spec(GUIDED_VIEWS[0]), expires_in_s=SESSION_TTL_S)

    @api.get("/captures/{capture_id}", response_model=S.CaptureState, tags=["capture"])
    def capture_state(capture_id: str):
        s = get_capture(capture_id)
        views = s["views"]
        n_id = sum(1 for v in views if spec_for(v.view_type).identity_view)
        nxt = s.get("next", GUIDED_VIEWS[0])
        return S.CaptureState(capture_id=capture_id, views=[_view_quality(v) for v in views],
                              accepted_views=len(views), can_identify=n_id >= MIN_VIEWS, next_view=_spec(nxt),
                              result=s.get("result_out"))

    @api.post("/captures/{capture_id}/views", response_model=S.ViewAdded, tags=["capture"])
    async def capture_view(capture_id: str, image: UploadFile = File(..., description="JPEG or PNG"),
                           view_key: str | None = Form(None, description="default: the view the server asked for"),
                           heading_deg: float | None = Form(None, ge=0, lt=360, description="compass heading")):
        """Add one photo. Rejected photos (blurry, dark, duplicate...) are reported and must be retaken."""
        s = get_capture(capture_id)
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
        vr = add_view(views, data, rgb, view_key, heading_deg)
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
    def capture_identify(capture_id: str, body: S.IdentifyRequest | None = None):
        """Decide existing / new / uncertain. If uncertain and another trunk view is available, nothing is
        stored and `action` is `capture_another_view`; otherwise the observation is stored."""
        body = body or S.IdentifyRequest()
        s = get_capture(capture_id)
        if s.get("result_out") is not None:
            return s["result_out"]
        views = s["views"]
        with db_lock:
            r = pipeline.identify(views, commit=False)
            if r.status == "recapture":
                return _result(r, "retake", views, s.get("next"))
            if r.status == "uncertain" and not body.force_commit:
                s["need_identity"] = True
                nxt = next_view({v.view_type for v in views}, need_identity=True)
                if nxt is not None:
                    s["next"] = nxt
                    return _result(r, "capture_another_view", views, nxt)
            r = pipeline.commit(views, r, fix=_fix(body.location))
        out = _result(r, "done" if r.status in ("existing", "new") else "review", views)
        s["result_out"] = out
        s["views"] = [ViewResult(v.index, v.view_type, v.quality, faces_blurred=v.faces_blurred) for v in views]
        return out

    @api.delete("/captures/{capture_id}", status_code=204, tags=["capture"])
    def cancel_capture(capture_id: str):
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
        commit: bool = Form(True, description="false = dry run, nothing stored")):
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
        views: list[ViewResult] = []
        for img, k, h in zip(images, keys, heads):
            data, rgb = await read_image(img)
            vr = add_view(views, data, rgb, k, h)
            del rgb
            views.append(vr)
        accepted = [v for v in views if v.accepted]
        loc = S.Location(lat=lat, lon=lon, accuracy_m=accuracy_m) if lat is not None else None
        with db_lock:
            r = pipeline.identify(accepted, commit=False)
            if r.status == "recapture":
                return _result(r, "retake", views)
            if commit:
                r = pipeline.commit(accepted, r, fix=_fix(loc))
        action = "done" if r.status in ("existing", "new") else "review"
        if r.status in ("rejected_species", "unsupported_species"):
            action = "done"
        return _result(r, action, views)

    # -------------------------------------------------------------- database
    @api.get("/trees", response_model=S.TreePage, tags=["trees"])
    def list_trees(species: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        trees = sorted(repo.list_trees(species), key=lambda t: t.last_seen_at, reverse=True)
        return S.TreePage(items=[tree_summary(t) for t in trees[offset: offset + limit]], total=len(trees),
                          limit=limit, offset=offset)

    @api.get("/trees/{tree_id}", response_model=S.TreeDetail, tags=["trees"])
    def tree_detail(tree_id: str):
        """A tree and its full observation history (oldest first)."""
        t = get_tree(tree_id)
        obs = repo.get_observations(tree_id)
        thumb = next((v.image_key for o in obs for v in o.views if v.image_key), None)
        return S.TreeDetail(**tree_summary(t, thumb).model_dump(), observations=[_observation(o) for o in obs])

    @api.patch("/trees/{tree_id}", response_model=S.TreeSummary, tags=["trees"])
    def update_tree(tree_id: str, body: S.TreeUpdate):
        get_tree(tree_id)
        repo.set_notes(tree_id, body.notes)
        return tree_summary(repo.get_tree(tree_id))

    @api.post("/trees/{tree_id}/merge", response_model=S.TreeDetail, tags=["trees"])
    def merge_trees(tree_id: str, body: S.MergeRequest):
        """Fix a duplicate: all observations of `duplicate_tree_id` move to this tree."""
        keep, drop = get_tree(tree_id), get_tree(body.duplicate_tree_id)
        if keep.tree_id == drop.tree_id:
            raise ApiError(400, "same_tree", "cannot merge a tree into itself")
        if keep.species != drop.species:
            raise ApiError(400, "species_mismatch", "trees have different species")
        with db_lock:
            repo.merge_trees(keep.tree_id, drop.tree_id)
            pipeline.index.invalidate(keep.species)
        return tree_detail(tree_id)

    @api.get("/observations", response_model=S.ObservationPage, tags=["observations"])
    def list_observations(status: list[str] | None = Query(None, description="e.g. status=uncertain"),
                          unassigned: bool = False, limit: int = Query(50, ge=1, le=500),
                          offset: int = Query(0, ge=0)):
        """Newest first. `?status=uncertain&unassigned=true` is the review queue."""
        items, total = repo.list_observations(status, unassigned, limit, offset)
        return S.ObservationPage(items=[_observation(o) for o in items], total=total, limit=limit, offset=offset)

    @api.get("/observations/{observation_id}", response_model=S.Observation, tags=["observations"])
    def get_observation(observation_id: str):
        o = repo.get_observation(observation_id)
        if o is None:
            raise ApiError(404, "observation_not_found", f"unknown observation {observation_id}")
        return _observation(o)

    @api.post("/observations/{observation_id}/assign", response_model=S.AssignResult, tags=["observations"])
    def assign_observation(observation_id: str, body: S.AssignRequest):
        """The user decides which tree an observation belongs to: resolve an uncertain one, or correct a
        wrong automatic decision (one tap on a candidate). `"new"` registers a new tree. A tree left with
        no observations is retired, never reused."""
        with db_lock:
            o = repo.get_observation(observation_id)
            if o is None:
                raise ApiError(404, "observation_not_found", f"unknown observation {observation_id}")
            if o.species not in REID_SUPPORTED or o.aggregated_embedding is None:
                raise ApiError(400, "not_assignable", "only identity observations of supported species can be "
                                                      "assigned")
            created = body.tree_id == "new"
            if created:
                tid = repo.create_tree(o.species, ID_PREFIX.get(o.species, "T"))
            else:
                t = get_tree(body.tree_id)
                if t.species != o.species:
                    raise ApiError(400, "species_mismatch", f"{t.tree_id} is {t.species}, observation is {o.species}")
                tid = t.tree_id
            if o.tree_id is None:
                repo.assign_observation(observation_id, tid, "user_confirmed")
            elif o.tree_id != tid:
                repo.reassign_observation(observation_id, tid)
            pipeline.index.invalidate(o.species)
        return S.AssignResult(observation_id=observation_id, tree_id=tid, created_tree=created)

    @api.get("/images/{key}", tags=["observations"], response_class=Response,
             responses={200: {"content": {"image/jpeg": {}}}})
    def image(key: str):
        if not key.replace(".", "").isalnum() or len(key) > 80:
            raise ApiError(400, "bad_key", "bad image key")
        try:
            data = pipeline.storage.get(key)
        except FileNotFoundError as e:
            raise ApiError(404, "image_not_found", "image not found") from e
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    app.include_router(api)
    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Hemlock Sentinel mobile API")
    ap.add_argument("--db", default=os.environ.get("HEMLOCK_DB", "runs/api/trees.sqlite"))
    ap.add_argument("--blobs", default=os.environ.get("HEMLOCK_BLOBS", "runs/api/blobs"))
    ap.add_argument("--model", default=os.environ.get("HEMLOCK_MODEL", str(DEFAULT_MODEL)))
    ap.add_argument("--calibration", default=os.environ.get("HEMLOCK_CALIBRATION", str(DEFAULT_CALIBRATION)))
    ap.add_argument("--demo", action="store_true", help="mock model (no weights); results are meaningless")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--cors", default=os.environ.get("HEMLOCK_CORS", "*"), help="comma-separated origins")
    args = ap.parse_args()
    if not args.demo and not Path(args.model).exists():
        raise SystemExit(f"model not found: {args.model} (use --demo to run without it)")
    import uvicorn

    pipe, demo = build_pipeline(args.db, args.blobs, None if args.demo else args.model, args.calibration)
    key = os.environ.get("HEMLOCK_API_KEY") or None
    print(f"Hemlock Sentinel API: model={'DEMO (mock)' if demo else pipe.runtime.version}, "
          f"auth={'X-API-Key' if key else 'off'}, docs at http://localhost:{args.port}/docs")
    uvicorn.run(create_api(pipe, demo, key, args.cors.split(",")), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
