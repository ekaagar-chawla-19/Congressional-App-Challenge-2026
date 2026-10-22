// HemlockID in the browser: decode a photo, preprocess it exactly like the Python server
// (src/hemlock_sentinel/preprocessing.py and pipeline/runtime.py), and run Model Delta or Model Gamma
// with ONNX Runtime Web, on the GPU (WebGPU) where the browser has it, otherwise on the CPU (WebAssembly).

import * as ort from '../vendor/ort/ort.all.min.mjs';

const MEAN = [0.485, 0.456, 0.406];
const STD = [0.229, 0.224, 0.225];
const DECODE_MIN_SIDE = 640;

export const MODELS = {
  delta: { key: 'delta', name: 'Model Delta', url: 'models/delta/model.onnx', size: 322, dim: 384, crops: 1 },
  gamma: { key: 'gamma', name: 'Model Gamma', url: 'models/gamma/model.onnx', size: 448, dim: 256, crops: 5, resize: 640 },
};

ort.env.wasm.wasmPaths = new URL('../vendor/ort/', import.meta.url).href;
// Several CPU threads need a cross-origin-isolated page (the service worker adds the headers).
ort.env.wasm.numThreads = globalThis.crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 4) : 1;

export const hasWebGPU = () => !!navigator.gpu;
export const threads = () => ort.env.wasm.numThreads;

// Python's round(): halves go to the even neighbour.
const pyRound = (x) => {
  const f = Math.floor(x);
  const d = x - f;
  return d > 0.5 ? f + 1 : d < 0.5 ? f : f % 2 === 0 ? f : f + 1;
};

/** Photo (Blob/File) -> RGB bytes, EXIF-rotated. Large JPEGs are first scaled by 1/2, 1/4 or 1/8 like
 *  Pillow's draft mode on the server, keeping the short side >= 640 px. */
export async function decode(blob) {
  const bmp = await createImageBitmap(blob, { imageOrientation: 'from-image' });
  let scale = 1;
  const m = Math.min(bmp.width, bmp.height);
  if (blob.type === 'image/jpeg') while (scale < 8 && Math.floor(m / (scale * 2)) >= DECODE_MIN_SIDE) scale *= 2;
  const w = Math.ceil(bmp.width / scale), h = Math.ceil(bmp.height / scale);
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(bmp, 0, 0, w, h);
  bmp.close?.();
  const rgba = ctx.getImageData(0, 0, w, h).data;
  const rgb = new Float32Array(w * h * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
    rgb[j] = rgba[i];
    rgb[j + 1] = rgba[i + 1];
    rgb[j + 2] = rgba[i + 2];
  }
  return { w, h, rgb };
}

// OpenCV INTER_AREA for shrinking: each output pixel is the area-weighted mean of the input pixels it covers.
function areaTaps(src, dst) {
  const s = src / dst;
  const taps = [];
  for (let i = 0; i < dst; i++) {
    const a = i * s, b = (i + 1) * s;
    const j0 = Math.floor(a), j1 = Math.min(src, Math.ceil(b));
    const idx = [], wts = [];
    for (let j = j0; j < j1; j++) {
      const o = Math.min(b, j + 1) - Math.max(a, j);
      if (o > 1e-9) { idx.push(j); wts.push(o / s); }
    }
    taps.push([idx, wts]);
  }
  return taps;
}

// OpenCV INTER_LINEAR for enlarging (half-pixel centres, edge clamped).
function linearTaps(src, dst) {
  const s = src / dst;
  const taps = [];
  for (let i = 0; i < dst; i++) {
    const x = Math.min(Math.max((i + 0.5) * s - 0.5, 0), src - 1);
    const j = Math.min(Math.floor(x), src - 2 < 0 ? 0 : src - 2);
    const f = x - j;
    taps.push(src === 1 ? [[0], [1]] : [[j, j + 1], [1 - f, f]]);
  }
  return taps;
}

/** Resize an RGB float image; the result is rounded to whole values like OpenCV's uint8 output. */
export function resize(img, nw, nh) {
  const tx = nw < img.w ? areaTaps(img.w, nw) : linearTaps(img.w, nw);
  const ty = nh < img.h ? areaTaps(img.h, nh) : linearTaps(img.h, nh);
  const tmp = new Float32Array(img.h * nw * 3);
  for (let y = 0; y < img.h; y++) {
    for (let x = 0; x < nw; x++) {
      const [idx, wts] = tx[x];
      let r = 0, g = 0, b = 0;
      for (let k = 0; k < idx.length; k++) {
        const p = (y * img.w + idx[k]) * 3, w = wts[k];
        r += img.rgb[p] * w; g += img.rgb[p + 1] * w; b += img.rgb[p + 2] * w;
      }
      const q = (y * nw + x) * 3;
      tmp[q] = r; tmp[q + 1] = g; tmp[q + 2] = b;
    }
  }
  const out = new Float32Array(nh * nw * 3);
  for (let y = 0; y < nh; y++) {
    const [idx, wts] = ty[y];
    for (let x = 0; x < nw; x++) {
      let r = 0, g = 0, b = 0;
      for (let k = 0; k < idx.length; k++) {
        const p = (idx[k] * nw + x) * 3, w = wts[k];
        r += tmp[p] * w; g += tmp[p + 1] * w; b += tmp[p + 2] * w;
      }
      const q = (y * nw + x) * 3;
      out[q] = Math.round(r); out[q + 1] = Math.round(g); out[q + 2] = Math.round(b);
    }
  }
  return { w: nw, h: nh, rgb: out };
}

// One size x size crop at (x0, y0) as a normalised CHW tensor slice.
function crop(img, x0, y0, size, out, offset = 0) {
  const plane = size * size;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const p = ((y0 + y) * img.w + x0 + x) * 3, q = offset + y * size + x;
      for (let c = 0; c < 3; c++) out[q + c * plane] = (img.rgb[p + c] / 255 - MEAN[c]) / STD[c];
    }
  }
  return out;
}

/** Model Delta's input: short side to 322, centre crop (to_network_input). */
export function deltaInput(img, size = 322) {
  const s = size / Math.min(img.w, img.h);
  const nh = Math.max(size, pyRound(img.h * s)), nw = Math.max(size, pyRound(img.w * s));
  const r = resize(img, nw, nh);
  return crop(r, Math.floor((nw - size) / 2), Math.floor((nh - size) / 2), size, new Float32Array(3 * size * size));
}

/** Model Gamma's input: short side to 640, five 448 px crops (centre + corners). */
export function gammaCrops(img, size = 448, short = 640) {
  const s = short / Math.min(img.w, img.h);
  const r = resize(img, pyRound(img.w * s), pyRound(img.h * s));
  const { w, h } = r;
  const pos = [[Math.floor((w - size) / 2), Math.floor((h - size) / 2)], [0, 0], [w - size, 0], [0, h - size], [w - size, h - size]];
  return pos.map(([x0, y0]) => crop(r, x0, y0, size, new Float32Array(3 * size * size)));
}

const unit = (v) => {
  let n = 0;
  for (const x of v) n += x * x;
  n = Math.sqrt(n) || 1;
  return Float32Array.from(v, (x) => x / n);
};

export const cosine = (a, b) => {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
};

function softmax(z) {
  const m = Math.max(...z);
  const e = z.map((x) => Math.exp(x - m));
  const t = e.reduce((a, b) => a + b, 0);
  return e.map((x) => x / t);
}

/** Load a model. backend: 'gpu' | 'cpu' | 'auto' (GPU when available, else CPU). */
export async function load(model, bytes, backend = 'auto') {
  const tries = backend === 'cpu' ? ['wasm'] : backend === 'gpu' ? ['webgpu'] : hasWebGPU() ? ['webgpu', 'wasm'] : ['wasm'];
  let last;
  for (const ep of tries) {
    try {
      const session = await ort.InferenceSession.create(bytes, { executionProviders: [ep], graphOptimizationLevel: 'all' });
      return { model, session, backend: ep === 'webgpu' ? 'GPU' : `CPU · ${threads()} thread${threads() > 1 ? 's' : ''}` };
    } catch (e) {
      last = e;
    }
  }
  throw last;
}

/** One decoded photo -> { embedding (unit length), hemlock probability (Delta only) }. Gamma runs its five crops
 *  one at a time (same result as a batch, less memory on a phone). */
export async function embed(loaded, img) {
  const { model, session } = loaded;
  const [embName, logitName] = session.outputNames;
  if (model.crops === 1) {
    const t = new ort.Tensor('float32', deltaInput(img, model.size), [1, 3, model.size, model.size]);
    const out = await session.run({ images: t });
    const e = unit(out[embName].data);
    const p = logitName ? softmax(Array.from(out[logitName].data))[0] : null;
    return { embedding: e, hemlock: p };
  }
  const mean = new Float32Array(model.dim);
  for (const c of gammaCrops(img, model.size, model.resize)) {
    const out = await session.run({ images: new ort.Tensor('float32', c, [1, 3, model.size, model.size]) });
    const e = unit(out[embName].data);
    for (let i = 0; i < mean.length; i++) mean[i] += e[i];
  }
  return { embedding: unit(mean), hemlock: null };
}

/** Fetch a file with download progress (bytes so far, total). The service worker keeps it for offline use. */
export async function download(url, onProgress) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  const total = Number(res.headers.get('content-length')) || 0;
  if (!res.body || !onProgress) return new Uint8Array(await res.arrayBuffer());
  const reader = res.body.getReader();
  const parts = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    got += value.length;
    onProgress(got, total);
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
