/**
 * Run the Hemlock Sentinel model ON THE PHONE (or any JS runtime) - same model, same decision.
 *
 * A port of the server pipeline (src/hemlock_sentinel/preprocessing.py, acquisition/quality.py,
 * species/inference.py, reid/multiview.py, reid/retrieval.py, reid/fusion.py) that works with
 * any ONNX Runtime JS binding passed in:
 *   web:          import * as ort from "onnxruntime-web"
 *   React Native: import * as ort from "onnxruntime-react-native"
 *   Node:         import * as ort from "onnxruntime-node"
 *
 *   const files = await api.downloadModel();                 // once; cache the bytes
 *   const model = await OnDeviceModel.create(ort, files.onnx, files.meta, files.calibration);
 *   const gallery = await api.gallery();                     // the forest's trees, for offline use
 *   const views = [await model.processView(rgba1, "trunk_north"), ...];
 *   const r = model.identify(views, gallery);                // existing / new / uncertain
 *
 * Images are { width, height, data, channels } pixel buffers (e.g. canvas ImageData, channels 4).
 * Not ported: the edge-density check ("no tree structure visible") and face blurring; the
 * server still runs both when the capture is synced. Parity with the server is checked by
 * client/test/parity.mjs on held-out BarkNet hemlocks.
 */
import type { components } from "./schema";

type Gallery = components["schemas"]["Gallery"];

export interface RgbImage {
  width: number;
  height: number;
  data: Uint8Array | Uint8ClampedArray;
  /** 3 = RGB, 4 = RGBA (alpha ignored) */
  channels: 3 | 4;
}

/** The subset of the ONNX Runtime JS API used here (identical in -web, -react-native, -node). */
export interface OrtLike {
  InferenceSession: { create(model: any, options?: any): Promise<any> };
  Tensor: new (type: "float32", data: Float32Array, dims: number[]) => any;
}

export interface ModelMeta {
  image_size: number;
  embedding_dim: number;
  species_labels: string[];
  version?: string;
}

export interface Fuser { feature_names: string[]; coef: number[]; intercept: number; mean: number[]; scale: number[] }
export interface Calibration {
  species_threshold: number;
  match_threshold: number;
  global_threshold: number;
  view_contradiction_margin: number;
  view_match_threshold: number | null;
  duplicate_cosine: number | null;
  duplicate_hard_cosine: number | null;
  fusers: Record<string, Fuser>;
}

export interface ViewResult {
  viewKey: string;
  accepted: boolean;
  problems: string[];
  warnings: string[];
  metrics: { laplacian_var: number; clipped_fraction: number; mean_luma: number };
  weight: number;
  embedding: Float32Array | null;
  speciesLogits: Float32Array | null;
  ms: number;
}

export interface OnDeviceCandidate { tree_id: string; probability: number; global: number; gap: number; agreement: number }
export interface OnDeviceResult {
  status: "existing" | "new" | "uncertain" | "rejected_species" | "unsupported_species" | "recapture";
  tree_id: string | null;
  probability: number | null;
  message: string;
  species: { label: string; confidence: number } | null;
  candidates: OnDeviceCandidate[];
  best_guess: { tree_id: string; probability: number } | null;
  contradicting_views: number[];
  on_device: true;
  model_version: string | null;
}

export const IDENTITY_VIEWS = ["trunk_north", "trunk_right", "trunk_right2", "trunk_right3", "trunk_north_high"];
export const REID_SUPPORTED = ["tsuga_canadensis"];
const MEAN = [0.485, 0.456, 0.406];
const STD = [0.229, 0.224, 0.225];
const DECODE_MIN_SIDE = 640;
const QUALITY = { minLaplacianVar: 25, maxClipped: 0.25, minLuma: 35, maxLuma: 225, analysisSide: 512 };
const TOP_K = 5;

// --------------------------------------------------------------- image ops
/** OpenCV-style INTER_AREA resize (box filter with fractional coverage), uint8 in/out, any channels. */
export function resizeArea(src: Uint8Array | Uint8ClampedArray, w: number, h: number, c: number,
                           nw: number, nh: number): Uint8Array {
  const sx = w / nw, sy = h / nh;
  const tmp = new Float32Array(nw * h * c);
  const xs = coverage(w, nw, sx);
  for (let y = 0; y < h; y++) {
    const row = y * w * c, orow = y * nw * c;
    for (let x = 0; x < nw; x++) {
      const { idx, wt } = xs[x];
      for (let ch = 0; ch < c; ch++) {
        let acc = 0;
        for (let k = 0; k < idx.length; k++) acc += src[row + idx[k] * c + ch] * wt[k];
        tmp[orow + x * c + ch] = acc;
      }
    }
  }
  const out = new Uint8Array(nw * nh * c);
  const ys = coverage(h, nh, sy);
  for (let y = 0; y < nh; y++) {
    const { idx, wt } = ys[y];
    for (let x = 0; x < nw * c; x++) {
      let acc = 0;
      for (let k = 0; k < idx.length; k++) acc += tmp[idx[k] * nw * c + x] * wt[k];
      out[y * nw * c + x] = Math.min(255, Math.max(0, Math.round(acc)));
    }
  }
  return out;
}

function coverage(n: number, nn: number, scale: number) {
  const res: { idx: number[]; wt: number[] }[] = [];
  for (let o = 0; o < nn; o++) {
    const a = o * scale, b = Math.min(n, (o + 1) * scale);
    const idx: number[] = [], wt: number[] = [];
    for (let i = Math.floor(a); i < Math.ceil(b - 1e-9); i++) {
      const cov = Math.min(b, i + 1) - Math.max(a, i);
      if (cov > 1e-9) { idx.push(i); wt.push(cov / (b - a)); }
    }
    res.push({ idx, wt });
  }
  return res;
}

function toRgb(img: RgbImage): Uint8Array {
  if (img.channels === 3) return Uint8Array.from(img.data);
  const n = img.width * img.height, out = new Uint8Array(n * 3);
  for (let i = 0; i < n; i++) { out[3 * i] = img.data[4 * i]; out[3 * i + 1] = img.data[4 * i + 1]; out[3 * i + 2] = img.data[4 * i + 2]; }
  return out;
}

/** Mimics the server's JPEG decode-at-reduced-scale (DCT draft): halve while the short side stays >= 640. */
export function draftDownscale(rgb: Uint8Array, w: number, h: number): { rgb: Uint8Array; w: number; h: number } {
  let s = 1;
  while (s < 8 && Math.floor(Math.min(w, h) / (s * 2)) >= DECODE_MIN_SIDE) s *= 2;
  if (s === 1) return { rgb, w, h };
  const nw = Math.ceil(w / s), nh = Math.ceil(h / s);
  return { rgb: resizeArea(rgb, w, h, 3, nw, nh), w: nw, h: nh };
}

/** RGB uint8 -> float32 (1, 3, size, size), resize short side to size + centre crop + ImageNet norm. */
export function toNetworkInput(rgb: Uint8Array, w: number, h: number, size: number): Float32Array {
  const s = size / Math.min(w, h);
  const nh = Math.max(size, Math.round(h * s)), nw = Math.max(size, Math.round(w * s));
  const r = resizeArea(rgb, w, h, 3, nw, nh);
  const y0 = Math.floor((nh - size) / 2), x0 = Math.floor((nw - size) / 2);
  const out = new Float32Array(3 * size * size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = ((y + y0) * nw + (x + x0)) * 3;
    for (let ch = 0; ch < 3; ch++) out[ch * size * size + y * size + x] = (r[i + ch] / 255 - MEAN[ch]) / STD[ch];
  }
  return out;
}

/** Blur / exposure checks at a fixed 512 px analysis scale, as on the server. */
export function assessQuality(rgb: Uint8Array, w: number, h: number) {
  let g: Uint8Array = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) g[i] = Math.round(0.299 * rgb[3 * i] + 0.587 * rgb[3 * i + 1] + 0.114 * rgb[3 * i + 2]);
  const s = QUALITY.analysisSide / Math.max(w, h);
  if (s < 1) { const nw = Math.trunc(w * s), nh = Math.trunc(h * s); g = resizeArea(g, w, h, 1, nw, nh); w = nw; h = nh; }
  const at = (x: number, y: number) => g[reflect(y, h) * w + reflect(x, w)];
  let sum = 0, sum2 = 0, clipped = 0, blown = 0, luma = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const v = g[y * w + x];
    luma += v; if (v <= 3 || v >= 252) clipped++; if (v >= 252) blown++;
    const lap = at(x - 1, y) + at(x + 1, y) + at(x, y - 1) + at(x, y + 1) - 4 * v;
    sum += lap; sum2 += lap * lap;
  }
  const n = w * h, mean = sum / n;
  const metrics = { laplacian_var: sum2 / n - mean * mean, clipped_fraction: clipped / n, mean_luma: luma / n };
  const problems: string[] = [];
  if (metrics.laplacian_var < QUALITY.minLaplacianVar) problems.push("blurry: hold the device steady and tap to focus");
  // only bright clipping means over-exposed (a black frame is "too dark"), as on the server
  if (blown / n > QUALITY.maxClipped || metrics.mean_luma > QUALITY.maxLuma) problems.push("over-exposed: avoid pointing at the sun / bright sky");
  if (metrics.mean_luma < QUALITY.minLuma) problems.push("too dark: move to better light or use the torch");
  const weight = Math.min(1, Math.max(0.25, Math.log1p(metrics.laplacian_var) / Math.log1p(4 * QUALITY.minLaplacianVar)));
  return { metrics, problems, weight };
}

function reflect(i: number, n: number): number { // BORDER_REFLECT_101
  if (i < 0) return -i;
  if (i >= n) return 2 * n - i - 2;
  return i;
}

// ------------------------------------------------------------------ maths
function l2(v: Float32Array): Float32Array {
  let s = 0;
  for (const x of v) s += x * x;
  const n = Math.max(Math.sqrt(s), 1e-12), o = new Float32Array(v.length);
  for (let i = 0; i < v.length; i++) o[i] = v[i] / n;
  return o;
}
const dot = (a: Float32Array, b: Float32Array) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };
function softmax(z: Float32Array): number[] {
  const m = Math.max(...z), e = Array.from(z, (x) => Math.exp(x - m)), s = e.reduce((a, b) => a + b, 0);
  return e.map((x) => x / s);
}
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
/** base64 little-endian float32 (gallery format) -> Float32Array; no atob/Buffer needed. */
export function decodeEmbedding(b64: string): Float32Array {
  const clean = b64.replace(/=+$/, "");
  const u8 = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let bits = 0, n = 0, o = 0;
  for (const ch of clean) {
    bits = (bits << 6) | B64.indexOf(ch); n += 6;
    if (n >= 8) { n -= 8; u8[o++] = (bits >> n) & 0xff; }
  }
  return new Float32Array(u8.buffer, 0, Math.floor(o / 4));
}

// ------------------------------------------------------------------ model
export class OnDeviceModel {
  private constructor(private ort: OrtLike, private session: any, readonly meta: ModelMeta, readonly cal: Calibration) {}

  /** model: the hemlock.onnx bytes (web/Node) or a file path/URI (React Native). */
  static async create(ort: OrtLike, model: Uint8Array | ArrayBuffer | string, meta: ModelMeta, cal: Calibration,
                      sessionOptions: any = { executionProviders: ["wasm"] }): Promise<OnDeviceModel> {
    const session = await ort.InferenceSession.create(model, sessionOptions);
    return new OnDeviceModel(ort, session, meta, cal);
  }

  /** Quality checks + embedding + species logits for one photo. previous: earlier views of this capture. */
  async processView(img: RgbImage, viewKey: string, previous: ViewResult[] = []): Promise<ViewResult> {
    const t0 = Date.now();
    const d = draftDownscale(toRgb(img), img.width, img.height);
    const q = assessQuality(d.rgb, d.w, d.h);
    const res: ViewResult = { viewKey, accepted: q.problems.length === 0, problems: q.problems, warnings: [],
      metrics: q.metrics, weight: q.weight, embedding: null, speciesLogits: null, ms: 0 };
    if (res.accepted) {
      const size = this.meta.image_size;
      const x = new this.ort.Tensor("float32", toNetworkInput(d.rgb, d.w, d.h, size), [1, 3, size, size]);
      const out = await this.session.run({ images: x });
      res.embedding = new Float32Array(out.embedding.data);
      res.speciesLogits = new Float32Array(out.species_logits.data);
      const hard = this.cal.duplicate_hard_cosine ?? 0.97, soft = this.cal.duplicate_cosine ?? 0.9;
      for (const [i, p] of previous.entries()) {
        if (!p.embedding || p.viewKey === viewKey) continue;
        const cos = dot(l2(p.embedding), l2(res.embedding));
        if (cos > hard) { res.accepted = false; res.problems.push(`same as view ${i + 1}: move to the next position before capturing`); break; }
        if (cos > soft) res.warnings.push(`very similar to view ${i + 1}: make sure you moved to the next position`);
      }
    }
    res.ms = Date.now() - t0;
    return res;
  }

  /** The server's decision (species gate -> retrieval -> calibrated fusion), against a downloaded gallery. */
  identify(views: ViewResult[], gallery: Gallery | null): OnDeviceResult {
    const base = { candidates: [] as OnDeviceCandidate[], best_guess: null, contradicting_views: [] as number[],
      on_device: true as const, model_version: this.meta.version ?? null };
    const id = views.filter((v) => v.accepted && v.embedding && IDENTITY_VIEWS.includes(v.viewKey));
    if (id.length < 3) return { ...base, status: "recapture", tree_id: null, probability: null, species: null,
      message: `need 3 good trunk views, have ${id.length}` };
    const w = id.map((v) => v.weight);
    const wsum = w.reduce((a, b) => a + b, 0) || id.length;
    const labels = this.meta.species_labels;
    const mean = new Array(labels.length).fill(0);
    id.forEach((v, k) => softmax(v.speciesLogits!).forEach((p, j) => { mean[j] += (w[k] || 1) * p / wsum; }));
    const si = mean.indexOf(Math.max(...mean)), conf = mean[si];
    if (conf < this.cal.species_threshold)
      return { ...base, status: "rejected_species", tree_id: null, probability: null, species: { label: "unknown", confidence: conf },
        message: `species uncertain (${Math.round(conf * 100)}%); retake photos or species not supported` };
    const species = { label: labels[si], confidence: conf };
    if (!REID_SUPPORTED.includes(labels[si]))
      return { ...base, status: "unsupported_species", tree_id: null, probability: null, species,
        message: `${labels[si]}: individual tracking not supported yet` };

    const embs = id.map((v) => l2(v.embedding!));
    const agg = new Float32Array(embs[0].length);
    embs.forEach((e, k) => e.forEach((x, i) => { agg[i] += w[k] * x; }));
    const q = l2(agg);
    const names = gallery ? [...new Set(gallery.observations.map((o) => o.tree_id))] : [];
    if (!gallery || !names.length)
      return { ...base, status: "new", tree_id: null, probability: 0, species, message: "No trees in this forest yet: new tree" };
    const gal = gallery.observations.map((o) => ({ t: names.indexOf(o.tree_id), e: l2(decodeEmbedding(o.embedding_b64)) }));
    const treeScores = (v: Float32Array) => {
      const s = new Array(names.length).fill(-1);
      for (const g of gal) s[g.t] = Math.max(s[g.t], Math.min(1, Math.max(-1, dot(v, g.e))));
      return s;
    };
    const aggS = treeScores(q), viewS = embs.map(treeScores);
    const argmax = (a: number[]) => a.indexOf(Math.max(...a));
    const top = aggS.map((s, i) => [s, i]).sort((a, b) => b[0] - a[0]).slice(0, TOP_K).map((x) => x[1]);
    const scored: OnDeviceCandidate[] = top.map((ci) => {
      const others = aggS.filter((_, i) => i !== ci);
      const g = aggS[ci], gap = others.length ? g - Math.max(...others) : g;
      const agreement = viewS.filter((vs) => argmax(vs) === ci).length / viewS.length;
      return { tree_id: names[ci], probability: this.matchProbability({ global: g, gap, agreement }), global: g, gap, agreement };
    }).sort((a, b) => b.probability - a.probability);
    const best = scored[0], ci = names.indexOf(best.tree_id);
    const contra = viewS.map((vs, v) => [vs, v] as const).filter(([vs]) => argmax(vs) !== ci &&
      vs[argmax(vs)] - vs[ci] > this.cal.view_contradiction_margin).map(([, v]) => v + 1);
    const out = { ...base, candidates: scored, species, contradicting_views: contra, probability: best.probability };
    if (best.probability < this.cal.match_threshold) {
      if (this.cal.view_match_threshold != null) {
        let bv = -1, bt = 0, bs = -2;
        viewS.forEach((vs, v) => vs.forEach((s, t) => { if (s > bs) { bs = s; bv = v; bt = t; } }));
        if (bs >= this.cal.view_match_threshold)
          return { ...out, status: "uncertain", tree_id: null, best_guess: { tree_id: best.tree_id, probability: best.probability },
            message: `view ${bv + 1} alone matches ${names[bt]} but the full capture does not; re-take the views of this tree` };
      }
      return { ...out, status: "new", tree_id: null, message: "No reliable match: new tree" };
    }
    if (contra.length)
      return { ...out, status: "uncertain", tree_id: null, best_guess: { tree_id: best.tree_id, probability: best.probability },
        message: `views [${contra.join(", ")}] point to a different tree; capture another view` };
    return { ...out, status: "existing", tree_id: best.tree_id, message: `Matched existing tree ${best.tree_id}` };
  }

  private matchProbability(f: Record<string, number>): number {
    const key = ["global", "gap", "agreement"].filter((k) => k in f).join("+");
    const fz = this.cal.fusers[key];
    if (!fz) return f.global >= this.cal.global_threshold ? 1 : 0;
    let z = fz.intercept;
    fz.feature_names.forEach((n, i) => { z += ((f[n] - fz.mean[i]) / fz.scale[i]) * fz.coef[i]; });
    return 1 / (1 + Math.exp(-z));
  }
}
