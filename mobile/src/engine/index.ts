import { Asset } from 'expo-asset';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import type { SQLiteDatabase } from 'expo-sqlite';
import * as jpeg from 'jpeg-js';
import { NativeModules } from 'react-native';
import type { SpeciesCheck } from '../api';
import calibration from '../../assets/models/calibration.json';
import meta from '../../assets/models/hemlock.json';
import reference from '../../assets/check/reference.json';
import { bytesFromBase64, encodeEmbedding } from './codec';
import { OnDeviceModel, type Calibration, type Gallery, type OnDeviceResult, type RgbImage, type ViewResult } from './ondevice';

// Model Delta on the phone: the same network, preprocessing and calibrated decision as the server
// (ondevice.ts), so phone-only mode identifies trees with no computer. Needs ONNX Runtime's native module, which
// is in a development build of the app (npx expo run:ios) but not in Expo Go: there `available()` is false and
// the app falls back to picking the tree by hand, as before.

export const MODEL_VERSION = meta.version;
// The guided capture's order of trunk views (the model needs 3 identity views).
const VIEW_KEYS = ['trunk_north', 'trunk_right', 'trunk_right2', 'trunk_right3', 'trunk_north_high'];
const DECODE_MIN_SIDE = 640; // the server's JPEG draft decode keeps the short side at least this long

export const available = () => NativeModules.Onnxruntime != null;

let loading: Promise<OnDeviceModel> | null = null;
/** Load the model once (about 1 s); later calls reuse it. */
export function model(): Promise<OnDeviceModel> {
  if (!available()) return Promise.reject(new Error('The on-device model needs the HemlockID app build (not Expo Go).'));
  loading ??= (async () => {
    const ort = await import('onnxruntime-react-native'); // only now: importing it without the native module throws
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- Metro bundles assets through require()
    const asset = await Asset.fromModule(require('../../assets/models/hemlock.onnx')).downloadAsync();
    const path = (asset.localUri ?? asset.uri).replace(/^file:\/\//, '');
    return OnDeviceModel.create(ort, path, meta, calibration as unknown as Calibration, { executionProviders: ['cpu'] });
  })().catch((e) => {
    loading = null;
    throw e;
  });
  return loading;
}

/**
 * A photo as RGB pixels, upright (EXIF applied), at the size the server decodes it: libjpeg's draft mode scales by
 * 1/2, 1/4 or 1/8 while the short side stays >= 640 (preprocessing.decode_image), so a 12 MP photo becomes 756x1008.
 * Scaling natively first keeps the slow JavaScript JPEG decode small; the engine's own draft step is then a no-op.
 */
export async function decode(uri: string): Promise<RgbImage> {
  const full = await ImageManipulator.manipulate(uri).renderAsync();
  const { width: w, height: h } = full;
  let s = 1;
  while (s < 8 && Math.floor(Math.min(w, h) / (s * 2)) >= DECODE_MIN_SIDE) s *= 2;
  const ref = s > 1 ? await ImageManipulator.manipulate(uri).resize({ width: Math.floor(w / s), height: Math.floor(h / s) }).renderAsync() : full;
  const { base64 } = await ref.saveAsync({ format: SaveFormat.JPEG, compress: 0.95, base64: true });
  const img = jpeg.decode(bytesFromBase64(base64!), { useTArray: true, formatAsRGBA: false });
  return { width: img.width, height: img.height, data: img.data, channels: 3 };
}

/** Quality checks + fingerprint + species for the n-th photo of a scan (previous: the scan's earlier photos). */
export async function checkPhoto(uri: string, n: number, previous: ViewResult[]): Promise<ViewResult> {
  const m = await model();
  return m.processView(await decode(uri), VIEW_KEYS[n] ?? `extra_${n}`, previous);
}

/** Hemlock probability of one checked photo (species head), or null if the photo was rejected before the model. */
export function hemlockProbability(v: ViewResult): number | null {
  if (!v.speciesLogits) return null;
  const l = Array.from(v.speciesLogits), mx = Math.max(...l);
  const ex = l.map((x) => Math.exp(x - mx)), sum = ex.reduce((a, b) => a + b, 0);
  return ex[meta.species_labels.indexOf('tsuga_canadensis')] / sum;
}

// Same names as the server (species/labels.py COMMON_NAMES).
const COMMON_NAMES: Record<string, string> = {
  tsuga_canadensis: 'Eastern hemlock', pinus_strobus: 'Eastern white pine', pinus_resinosa: 'Red pine', pinus_rigida: 'Pitch pine',
  fagus_grandifolia: 'American beech', acer_rubrum: 'Red maple', acer_platanoides: 'Norway maple', populus_grandidentata: 'Bigtooth aspen',
};

/** "Is this a hemlock?" for one photo, on the phone: the same verdict as the server's POST /species-check. */
export async function speciesCheck(uri: string): Promise<SpeciesCheck> {
  const v = await checkPhoto(uri, 0, []);
  if (!v.speciesLogits) throw new Error(`Can't check that photo: ${v.problems.join('; ')}`);
  const l = Array.from(v.speciesLogits), mx = Math.max(...l);
  const ex = l.map((x) => Math.exp(x - mx)), sum = ex.reduce((a, b) => a + b, 0);
  const top = meta.species_labels.map((label, i) => ({ label, name: COMMON_NAMES[label] ?? label, probability: ex[i] / sum }))
    .sort((a, b) => b.probability - a.probability).slice(0, 3);
  const hp = ex[meta.species_labels.indexOf('tsuga_canadensis')] / sum;
  const th = (calibration as unknown as Calibration).species_threshold;
  const verdict = top[0].label === 'tsuga_canadensis' && hp >= th ? 'hemlock' : hp < 0.2 ? 'not_hemlock' : 'unsure';
  return {
    is_hemlock: verdict === 'hemlock', verdict, hemlock_probability: hp, threshold: th, species: top[0], top,
    quality: { index: 0, view_type: v.viewKey, accepted: v.accepted, problems: v.problems, warnings: v.warnings, metrics: v.metrics, hemlock_probability: hp, top_species: top[0] },
    message: '',
  };
}

/** The forest's trees as the model sees them: every stored fingerprint from this model version. */
export async function phoneGallery(db: SQLiteDatabase, forestId: number): Promise<Gallery> {
  const rows = await db.getAllAsync<{ tree_id: string; embedding_b64: string }>(
    'SELECT f.tree_id, f.embedding_b64 FROM fingerprints f JOIN trees t ON t.id = f.tree_id WHERE t.forest_id = ? AND f.model = ?', forestId, MODEL_VERSION);
  return { observations: rows };
}

/** Which tree these photos show, decided on the phone. fingerprints: to store with the tree it is saved to. */
export async function identifyOnPhone(views: ViewResult[], gallery: Gallery): Promise<{ result: OnDeviceResult; fingerprints: string[] }> {
  const m = await model();
  const result = m.identify(views, gallery);
  const fingerprints = views.filter((v) => v.accepted && v.embedding && VIEW_KEYS.includes(v.viewKey)).map((v) => encodeEmbedding(v.embedding!));
  return { result, fingerprints };
}

export { encodeEmbedding };
export type { ViewResult };

export type SelfCheck = { ok: boolean; cosine: number; hemlock: number | null; hemlockServer: number; loadMs: number; decodeMs: number; modelMs: number; size: [number, number] };

/**
 * Proves the on-device model works on this phone: runs it on a known photo and compares the fingerprint with what
 * the server computed for the same photo (assets/check, from scripts/web_reference.py). ok: cosine >= 0.995.
 */
export async function selfCheck(): Promise<SelfCheck> {
  const t0 = Date.now();
  const m = await model();
  const t1 = Date.now();
  const asset = await Asset.fromModule(require('../../assets/check/sample.jpg')).downloadAsync();
  const img = await decode(asset.localUri ?? asset.uri);
  const t2 = Date.now();
  const v = await m.processView(img, 'trunk_north', []);
  const t3 = Date.now();
  const ref = reference.embedding;
  let dot = 0, na = 0, nb = 0;
  v.embedding?.forEach((x, i) => { dot += x * ref[i]; na += x * x; nb += ref[i] * ref[i]; });
  const cosine = v.embedding ? dot / Math.sqrt(na * nb) : 0;
  return { ok: cosine >= 0.995, cosine, hemlock: hemlockProbability(v), hemlockServer: reference.hemlock_probability,
    loadMs: t1 - t0, decodeMs: t2 - t1, modelMs: t3 - t2, size: [img.width, img.height] };
}
