"""End-to-end inference: guided views -> species gate -> embedding -> retrieval -> decision -> persistence.

Memory/latency choices (measured in benchmarks/):
* each view is decoded once; the decoded array is reused for quality checks,
  local features and the network input, then dropped — only the per-view
  embedding (D floats) and the original JPEG bytes are kept until commit;
* views are embedded as they are captured (the user is walking to the next
  view anyway), so "identify" only does retrieval + decision;
* local (keypoint) matching runs only against the top-k global candidates.
"""

from __future__ import annotations

import io
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from ..acquisition.interfaces import GPS, DepthFrame, EnvironmentalSensors, Frame, ModelRuntime, Storage
from ..acquisition.privacy import blur_faces
from ..acquisition.protocol import GUIDED_VIEWS, MIN_VIEWS, is_identity_view, spec_for
from ..acquisition.quality import QualityReport, QualityThresholds, assess, heading_problem
from ..database.indexing import IndexCache
from ..database.models import ObservationRecord, ViewRecord
from ..database.repository import TreeRepository
from ..preprocessing import to_network_input
from ..reid.calibration import Calibration
from ..reid.fusion import IdentityDecision, candidate_features, decide
from ..reid.local_matching import KeypointMatcher, LocalFeatures, profile_similarity, trunk_profile_from_depth, Intrinsics
from ..reid.multiview import aggregate_mean, l2_normalize
from ..species.inference import SpeciesResult, classify_observation
from ..species.labels import ID_PREFIX


@dataclass
class ViewResult:
    index: int
    view_type: str
    quality: QualityReport
    embedding: np.ndarray | None = None
    species_logits: np.ndarray | None = None
    local: LocalFeatures | None = None
    image_bytes: bytes | None = None
    depth: DepthFrame | None = None
    heading_deg: float | None = None
    faces_blurred: int = 0
    duplicate_of: int | None = None

    @property
    def accepted(self) -> bool:
        return self.quality.ok and self.duplicate_of is None


@dataclass
class ObservationResult:
    status: str  # existing | new | uncertain | rejected_species | unsupported_species | recapture
    tree_id: str | None
    species: SpeciesResult | None
    decision: IdentityDecision | None
    observation_id: str | None
    message: str
    timings_ms: dict = field(default_factory=dict)
    aggregated: np.ndarray | None = None
    committed: bool = False


@dataclass
class PipelineConfig:
    top_k: int = 5
    # Off by default: on BarkNet the RootSIFT signal added nothing over the fine-tuned
    # global embedding (fused test AUC 0.890 vs 0.892) at ~1.4 s and 54 KB/view
    # (docs/experiments.md E-local). Re-test on field data captured with the protocol.
    use_local_matching: bool = False
    use_depth: bool = True
    store_images: bool = True
    blur_faces: bool = True
    quality: QualityThresholds = field(default_factory=QualityThresholds)


class HemlockSentinel:
    def __init__(self, runtime: ModelRuntime, repo: TreeRepository, storage: Storage, calibration: Calibration,
                 config: PipelineConfig | None = None, gps: GPS | None = None,
                 sensors: EnvironmentalSensors | None = None):
        self.runtime = runtime
        self.repo = repo
        self.storage = storage
        self.cal = calibration
        self.cfg = config or PipelineConfig()
        if calibration.duplicate_cosine is not None:
            self.cfg.quality.warn_duplicate_cosine = calibration.duplicate_cosine
        if calibration.duplicate_hard_cosine is not None:
            self.cfg.quality.max_duplicate_cosine = calibration.duplicate_hard_cosine
        self.gps = gps
        self.sensors = sensors
        self.index = IndexCache(repo, runtime.embedding_dim)
        self.matcher = KeypointMatcher() if self.cfg.use_local_matching else None
        self._local_cache: dict[str, LocalFeatures] = {}

    # ------------------------------------------------------------------ views
    def process_view(self, frame: Frame, index: int, previous: list[ViewResult] | None = None,
                     depth: DepthFrame | None = None, view_key: str | None = None) -> ViewResult:
        """index: position in this capture; view_key: protocol view (default: GUIDED_VIEWS[index])."""
        spec = spec_for(view_key) if view_key else GUIDED_VIEWS[min(index, len(GUIDED_VIEWS) - 1)]
        rgb = frame.rgb
        q = assess(rgb, self.cfg.quality)
        vr = ViewResult(index, spec.key, q, depth=depth, heading_deg=frame.heading_deg)
        hp = heading_problem(spec.key, frame.heading_deg, {p.view_type: p.heading_deg for p in previous or []},
                             self.cfg.quality)
        if hp:
            q.problems.append(hp)
            q.ok = False
        if not q.ok:
            return vr
        faces = 0
        if self.cfg.blur_faces:
            rgb, faces = blur_faces(rgb)
        vr.faces_blurred = faces
        x = to_network_input(rgb, self.runtime.input_size)[None]
        emb, logits = self.runtime.run(x)
        vr.embedding, vr.species_logits = emb[0], logits[0]
        for p in previous or []:
            if p.embedding is None:
                continue
            cos = float(l2_normalize(p.embedding) @ l2_normalize(vr.embedding))
            if cos > self.cfg.quality.max_duplicate_cosine:
                vr.duplicate_of = p.index
                q.problems.append(f"same as view {p.index + 1}: move to the next position before capturing")
                q.ok = False
                return vr
            if cos > self.cfg.quality.warn_duplicate_cosine:
                q.warnings.append(f"very similar to view {p.index + 1}: make sure you moved to the next position")
        if self.matcher is not None and spec.identity_view:
            vr.local = self.matcher.extract(rgb)
        if self.cfg.store_images:
            if faces or frame.encoded is None:
                vr.image_bytes = _encode_jpeg(rgb)
            else:
                vr.image_bytes = frame.encoded  # store the original bytes, no re-encode
        return vr

    # --------------------------------------------------------------- identify
    def identify(self, views: list[ViewResult], commit: bool = True, now: float | None = None) -> ObservationResult:
        t0 = time.perf_counter()
        now = time.time() if now is None else now
        good = [v for v in views if v.accepted]
        id_views = [v for v in good if _is_identity_view(v.view_type)]
        if len(id_views) < MIN_VIEWS:
            return ObservationResult("recapture", None, None, None, None,
                                     f"need {MIN_VIEWS} good trunk views, have {len(id_views)}")
        species = classify_observation(np.stack([v.species_logits for v in id_views]), self.cal.species_threshold,
                                       self.runtime.species_labels, np.array([v.quality.weight for v in id_views]))
        if species.species == "unknown":
            return self._finish(views, species, None, "rejected_species", None,
                                f"species uncertain ({species.confidence:.0%}); retake photos or species not supported",
                                commit, now, t0)
        if not species.reid_allowed:
            return self._finish(views, species, None, "unsupported_species", None,
                                f"{species.common_name}: individual tracking not supported yet", commit, now, t0)

        embs = np.stack([v.embedding for v in id_views])
        agg = aggregate_mean(embs, np.array([v.quality.weight for v in id_views]))
        index = self.index.get(species.species)
        t_ret = time.perf_counter()
        if index.n_trees == 0:
            decision = decide([], self.cal)
        else:
            names = index.tree_names()
            agg_scores = index.tree_scores(agg)[0]
            view_scores = index.tree_scores(embs)
            top = np.argsort(-agg_scores)[: self.cfg.top_k]
            feats = []
            for i in top:
                tid = names[i]
                local = self._local_score(tid, id_views) if self.matcher is not None else None
                structure = self._structure_score(tid, id_views) if self.cfg.use_depth else None
                feats.append((tid, candidate_features(agg_scores, view_scores, names, tid, local, structure)))
            decision = decide(feats, self.cal, view_scores, names)
        timings = {"retrieval_decision_ms": (time.perf_counter() - t_ret) * 1000}
        msg = {"existing": f"Matched existing tree {decision.tree_id}",
               "new": "No reliable match: registering a new tree",
               "uncertain": decision.reason}[decision.kind]
        res = self._finish(views, species, decision, decision.kind, agg, msg, False, now, t0)
        res.timings_ms.update(timings)
        if commit:
            self.commit(views, res, now)
        return res

    # ---------------------------------------------------------------- helpers
    def _local_score(self, tree_id: str, views: list[ViewResult]) -> float | None:
        q = [v.local for v in views if v.local is not None]
        g = []
        for gv in self.repo.gallery_views(tree_id):
            if gv.local_features_key:
                if gv.local_features_key not in self._local_cache:
                    d = np.load(io.BytesIO(self.storage.get(gv.local_features_key)))
                    self._local_cache[gv.local_features_key] = LocalFeatures(d["kp"], d["desc"])
                g.append(self._local_cache[gv.local_features_key])
        if not q or not g:
            return None
        return self.matcher.score(q, g)

    def _structure_score(self, tree_id: str, views: list[ViewResult]) -> float | None:
        qd = [v.depth for v in views if v.depth is not None]
        if not qd:
            return None
        gd = [gv.depth_key for gv in self.repo.gallery_views(tree_id) if gv.depth_key]
        if not gd:
            return None
        qp = trunk_profile_from_depth(qd[0].depth_m, Intrinsics(qd[0].fx, qd[0].fy, qd[0].cx, qd[0].cy))
        best = float("nan")
        for key in gd:
            d = np.load(io.BytesIO(self.storage.get(key)))
            gp = trunk_profile_from_depth(d["depth"], Intrinsics(*d["K"]))
            s = profile_similarity(qp, gp, tol_m=float(d["tol"]) if "tol" in d else 0.01)
            if not np.isnan(s) and (np.isnan(best) or s > best):
                best = s
        return None if np.isnan(best) else best

    def _finish(self, views, species, decision, status, agg, message, commit, now, t0) -> ObservationResult:
        tree_id = decision.tree_id if decision is not None and decision.kind == "existing" else None
        res = ObservationResult(status, tree_id, species, decision, None, message,
                                {"identify_total_ms": (time.perf_counter() - t0) * 1000}, agg)
        if commit:
            self.commit(views, res, now)
        return res

    def commit(self, views: list[ViewResult], res: ObservationResult, now: float | None = None) -> ObservationResult:
        """Persist an identification result (new tree ID, observation, views, blobs). Idempotent."""
        if res.committed or res.status == "recapture":
            return res
        now = time.time() if now is None else now
        species, decision, status, agg = res.species, res.decision, res.status, res.aggregated
        if status == "new":
            res.tree_id = self.repo.create_tree(species.species, ID_PREFIX.get(species.species, "T"), now)
            res.message = f"New tree registered as {res.tree_id}"
        fix = self.gps.fix() if self.gps else None
        env = self.sensors.read().values if self.sensors else {}
        vrecs = []
        for v in views:
            if not v.accepted:
                continue
            img_key = self.storage.put(v.image_bytes, ".jpg") if v.image_bytes else None
            lf_key = None
            if v.local is not None:
                buf = io.BytesIO()
                np.savez_compressed(buf, kp=v.local.keypoints, desc=v.local.descriptors)
                lf_key = self.storage.put(buf.getvalue(), ".npz")
            d_key = None
            if v.depth is not None:
                buf = io.BytesIO()
                np.savez_compressed(buf, depth=v.depth.depth_m.astype(np.float16),
                                    K=np.array([v.depth.fx, v.depth.fy, v.depth.cx, v.depth.cy]))
                d_key = self.storage.put(buf.getvalue(), ".npz")
            vrecs.append(ViewRecord(v.index, v.view_type, img_key, v.embedding,
                                    {**v.quality.metrics, "weight": v.quality.weight,
                                     "faces_blurred": v.faces_blurred}, d_key, lf_key, v.heading_deg))
        obs = ObservationRecord(
            uuid.uuid4().hex, res.tree_id if status in ("existing", "new") else None, now, status,
            species.species if species else None, species.confidence if species else None,
            decision.probability if decision else None, agg,
            fix.lat if fix else None, fix.lon if fix else None, fix.accuracy_m if fix else None,
            getattr(self.runtime, "version", None), env,
            {"candidates": decision.candidates if decision else [],
             "contradicting_views": decision.consistency.contradicting_views
             if decision and decision.consistency else []},
            vrecs)
        res.observation_id = self.repo.add_observation(obs)
        if obs.tree_id is not None and agg is not None:
            self.index.add(species.species, obs.tree_id, agg, res.observation_id)
        res.committed = True
        return res


def _is_identity_view(view_type: str) -> bool:
    return is_identity_view(view_type)


def _encode_jpeg(rgb: np.ndarray, quality: int = 92) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()
