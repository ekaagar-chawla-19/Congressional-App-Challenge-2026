"""Handheld web app: guided multi-view capture + identification + tree history.

One small FastAPI process serves a single mobile page (no front-end framework)
and the JSON API. It runs on the handheld itself (Raspberry Pi + camera,
browser in kiosk mode) or on a laptop that a phone connects to.

Run:  hemlock-app --db runs/app/trees.sqlite --model runs/export/hemlock.onnx
      (no --model -> DEMO mode with a mock model; the UI shows a banner)
Phones only allow camera access over HTTPS (or localhost); see docs/deployment.md.
"""

from __future__ import annotations

import argparse
import os
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ..acquisition.interfaces import Frame
from ..acquisition.mocks import LocalFileStorage
from ..acquisition.protocol import GUIDED_VIEWS, MAX_TOTAL_VIEWS, MAX_VIEWS, MIN_VIEWS, next_view, spec_for
from ..database.repository import TreeRepository
from ..pipeline.inference import HemlockSentinel, ObservationResult, PipelineConfig, ViewResult
from ..preprocessing import decode_image
from ..reid.calibration import Calibration
from ..species.labels import COMMON_NAMES, ID_PREFIX

STATIC = Path(__file__).parent / "static"
SESSION_TTL_S = 30 * 60


class Sessions:
    """In-memory capture sessions (a few MB each; expire after 30 min)."""

    def __init__(self):
        self._d: dict[str, dict] = {}
        self._lock = threading.Lock()

    def new(self) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._gc()
            self._d[sid] = {"views": [], "t": time.time()}
        return sid

    def get(self, sid: str) -> dict:
        with self._lock:
            s = self._d.get(sid)
            if s is None:
                raise HTTPException(404, "capture session not found or expired")
            s["t"] = time.time()
            return s

    def drop(self, sid: str) -> None:
        with self._lock:
            self._d.pop(sid, None)

    def _gc(self) -> None:
        now = time.time()
        for k in [k for k, v in self._d.items() if now - v["t"] > SESSION_TTL_S]:
            del self._d[k]


def _view_json(v: ViewResult) -> dict:
    return {"index": v.index, "view_type": v.view_type, "accepted": v.accepted, "problems": v.quality.problems,
            "warnings": v.quality.warnings,
            "metrics": {k: round(x, 4) for k, x in v.quality.metrics.items()}, "faces_blurred": v.faces_blurred}


def _result_json(r: ObservationResult) -> dict:
    out = {"status": r.status, "tree_id": r.tree_id, "message": r.message, "observation_id": r.observation_id,
           "timings_ms": {k: round(v, 1) for k, v in r.timings_ms.items()}}
    if r.species:
        out["species"] = {"label": r.species.species, "name": r.species.common_name,
                          "confidence": round(r.species.confidence, 4)}
    if r.decision:
        out["probability"] = round(r.decision.probability, 4)
        out["candidates"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()}
                             for c in r.decision.candidates[:5]]
        if r.decision.consistency:
            c = r.decision.consistency
            out["consistency"] = {"per_view_top": c.per_view_top, "agreement": round(c.agreement, 3),
                                  "contradicting_views": [i + 1 for i in c.contradicting_views]}
    return out


def create_app(pipeline: HemlockSentinel, demo: bool = False) -> FastAPI:
    app = FastAPI(title="Hemlock Sentinel")
    sessions = Sessions()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/protocol")
    def protocol():
        return {"views": [asdict(v) for v in GUIDED_VIEWS], "min_views": MIN_VIEWS, "max_views": MAX_VIEWS,
                "max_total_views": MAX_TOTAL_VIEWS,
                "demo": demo, "model_version": getattr(pipeline.runtime, "version", "?")}

    @app.post("/api/session")
    def new_session():
        return {"session_id": sessions.new(), "next": asdict(GUIDED_VIEWS[0])}

    @app.post("/api/session/{sid}/view")
    async def add_view(sid: str, image: UploadFile = File(...), heading_deg: float | None = Form(None),
                       view_key: str | None = Form(None)):
        s = sessions.get(sid)
        data = await image.read()
        if len(data) > 25_000_000:
            raise HTTPException(413, "image too large")
        try:
            rgb = decode_image(data)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"cannot decode image: {e}") from e
        views: list[ViewResult] = s["views"]
        captured = {v.view_type for v in views}
        if view_key is None:  # default: the view the server asked for last
            nxt = s.get("next") or next_view(captured)
            if nxt is None:
                raise HTTPException(400, "all views captured")
            view_key = nxt.key
        try:
            spec_for(view_key)
        except KeyError as e:
            raise HTTPException(400, f"unknown view {view_key}") from e
        if len(views) >= MAX_TOTAL_VIEWS:
            raise HTTPException(400, f"at most {MAX_TOTAL_VIEWS} views")
        prev = [v for v in views if v.view_type != view_key]
        vr = pipeline.process_view(Frame(rgb, time.time(), encoded=data, heading_deg=heading_deg),
                                   len(prev), prev, view_key=view_key)
        del rgb
        if vr.accepted:
            s["views"] = prev + [vr]
            captured = {v.view_type for v in s["views"]}
            s["next"] = next_view(captured, need_identity=s.get("need_identity", False))
        else:
            s["next"] = spec_for(view_key)  # retake the same view
        n_std = sum(1 for v in s["views"] if v.view_type in {g.key for g in GUIDED_VIEWS})
        n_id = sum(1 for v in s["views"] if spec_for(v.view_type).identity_view)
        nxt = s["next"]
        return {"view": _view_json(vr), "accepted_views": len(s["views"]), "progress": min(1.0, n_std / MAX_VIEWS),
                "can_identify": n_id >= MIN_VIEWS, "next": asdict(nxt) if nxt else None}

    @app.post("/api/session/{sid}/identify")
    def identify(sid: str, force_commit: bool = Form(False)):
        s = sessions.get(sid)
        views = s["views"]
        r = pipeline.identify(views, commit=False)
        # Ambiguous: ask for another TRUNK view while any remain (more trunk views is the
        # measured lever), otherwise store unassigned for user review (never auto-merge).
        if r.status == "uncertain" and not force_commit:
            s["need_identity"] = True
            nxt = next_view({v.view_type for v in views}, need_identity=True)
            if nxt is not None:
                s["next"] = nxt
                out = _result_json(r)
                out["action"] = "capture_another_view"
                out["next"] = asdict(nxt)
                return out
        if r.status == "recapture":
            return {**_result_json(r), "action": "retake"}
        r = pipeline.commit(views, r)
        s["result"] = r
        out = _result_json(r)
        out["action"] = "done" if r.status in ("existing", "new") else "review"
        return out

    @app.post("/api/session/{sid}/resolve")
    def resolve(sid: str, tree_id: str = Form(...)):
        """User resolution of an 'uncertain' observation: an existing tree id, or 'new'."""
        s = sessions.get(sid)
        r: ObservationResult | None = s.get("result")
        if r is None or r.observation_id is None or r.status != "uncertain":
            raise HTTPException(400, "nothing to resolve")
        if tree_id == "new":
            tree_id = pipeline.repo.create_tree(r.species.species, ID_PREFIX.get(r.species.species, "T"))
        elif pipeline.repo.get_tree(tree_id) is None:
            raise HTTPException(404, "unknown tree")
        pipeline.repo.assign_observation(r.observation_id, tree_id, "user_confirmed")
        pipeline.index.invalidate(r.species.species)
        sessions.drop(sid)
        return {"tree_id": tree_id}

    @app.post("/api/session/{sid}/correct")
    def correct(sid: str, tree_id: str = Form(...)):
        """User says the committed observation is actually tree `tree_id` (one-tap correction
        from the candidate list). Moves the observation; a tree created by this observation
        alone is retired (merged), never reused."""
        s = sessions.get(sid)
        r: ObservationResult | None = s.get("result")
        if r is None or r.observation_id is None:
            raise HTTPException(400, "nothing to correct")
        if pipeline.repo.get_tree(tree_id) is None:
            raise HTTPException(404, "unknown tree")
        pipeline.repo.reassign_observation(r.observation_id, tree_id)
        pipeline.index.invalidate(r.species.species)
        sessions.drop(sid)
        return {"tree_id": tree_id}

    @app.get("/api/trees")
    def trees():
        return [{"tree_id": t.tree_id, "species": t.species, "name": COMMON_NAMES.get(t.species, t.species),
                 "created_at": t.created_at, "last_seen_at": t.last_seen_at,
                 "observation_count": t.observation_count} for t in pipeline.repo.list_trees()]

    @app.get("/api/trees/{tree_id}")
    def tree(tree_id: str):
        t = pipeline.repo.get_tree(tree_id)
        if t is None:
            raise HTTPException(404, "unknown tree")
        obs = pipeline.repo.get_observations(tree_id)
        return {"tree_id": t.tree_id, "species": t.species, "observation_count": t.observation_count,
                "observations": [{"observation_id": o.observation_id, "timestamp": o.timestamp,
                                  "decision": o.decision, "match_probability": o.match_probability,
                                  "lat": o.lat, "lon": o.lon,
                                  "images": [v.image_key for v in o.views if v.image_key]} for o in obs]}

    @app.get("/api/image/{key}")
    def image(key: str):
        if not key.replace(".", "").isalnum():
            raise HTTPException(400, "bad key")
        try:
            return Response(pipeline.storage.get(key), media_type="image/jpeg")
        except FileNotFoundError as e:
            raise HTTPException(404, "not found") from e

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def build_pipeline(db: str, blobs: str, model: str | None, calibration: str | None) -> tuple[HemlockSentinel, bool]:
    from ..pipeline.runtime import MockRuntime, OnnxRuntime, TorchRuntime

    demo = model is None
    if demo:
        runtime = MockRuntime(input_size=96, embedding_dim=256)
        cal = Calibration(species_threshold=0.5, global_threshold=0.8, match_threshold=0.5,
                          view_contradiction_margin=0.05, view_match_threshold=0.5,
                          provenance={"note": "DEMO calibration for the mock model; not validated"})
    else:
        runtime = OnnxRuntime(model) if model.endswith(".onnx") else TorchRuntime(model)
        if calibration is None:
            raise SystemExit("--calibration is required with a real model (thresholds must be validated)")
        cal = Calibration.load(calibration)
    repo = TreeRepository(db)
    storage = LocalFileStorage(blobs)
    return HemlockSentinel(runtime, repo, storage, cal, PipelineConfig()), demo


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="runs/app/trees.sqlite")
    ap.add_argument("--blobs", default="runs/app/blobs")
    ap.add_argument("--model", default=os.environ.get("HEMLOCK_MODEL"))
    ap.add_argument("--calibration", default=os.environ.get("HEMLOCK_CALIBRATION"))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--ssl-certfile")
    ap.add_argument("--ssl-keyfile")
    args = ap.parse_args()
    import uvicorn

    pipe, demo = build_pipeline(args.db, args.blobs, args.model, args.calibration)
    uvicorn.run(create_app(pipe, demo), host=args.host, port=args.port,
                ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile)


if __name__ == "__main__":
    main()
