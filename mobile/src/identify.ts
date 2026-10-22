import * as Location from 'expo-location';
import type { SQLiteDatabase } from 'expo-sqlite';
import * as api from './api';
import { useApp } from './device';
import * as engine from './engine';
import type { OnDeviceResult } from './engine/ondevice';
import { useModels } from './models';
import type { TreeRow } from './data';
import { isServer, useSession } from './session';
import { speciesName } from './species';

export type Match = { tree: TreeRow; score: number };
// `server` is set when a model ran: hemlock-api's decision, or the on-device model's (onPhone; nothing stored yet).
// offline: no model ran (Expo Go without a server); matches are the forest's trees, unscored, for a manual pick.
export type Identification = { matches: Match[]; server?: api.IdentifyResult; offline?: boolean; onPhone?: boolean };

export async function identify(photos: string[], trees: TreeRow[], done?: api.IdentifyResult | null, db?: SQLiteDatabase): Promise<Identification> {
  if (done) return { matches: matchesFrom(done, trees), server: done };
  // Phone-only mode: the photos were checked by the on-device model while scanning; decide here, no computer.
  const views = useApp.getState().views;
  if (!isServer() && views && db && engine.available()) {
    const gallery = await engine.phoneGallery(db, useSession.getState().forest?.id ?? -1);
    const { result, fingerprints } = await engine.identifyOnPhone(views, gallery);
    useApp.getState().setScan({ fingerprints: { model: engine.MODEL_VERSION, embeddings: fingerprints } });
    const r = asResult(result, engine.speciesSummary(views));
    return { matches: matchesFrom(r, trees), server: r, onPhone: true };
  }
  if (isServer()) {
    const r = await api.identify(photos, await quickFix(), useModels.getState().chosen ?? undefined, useApp.getState().sensors?.sensors ?? null);
    return { matches: matchesFrom(r, trees), server: r };
  }
  // The model runs on the server. Offline there is no identification: never invent a match score.
  return { matches: trees.map((tree) => ({ tree, score: NaN })), offline: true };
}

// The on-device decision in the server's shape, so the result screen treats both alike (nothing stored yet:
// the visit is saved on the phone after the health check).
function asResult(r: OnDeviceResult, scores: ReturnType<typeof engine.speciesSummary>): api.IdentifyResult {
  const sp = r.species;
  // Shown on the result: the photos' top species and hemlock % (also when the species is too uncertain to name).
  return {
    status: r.status, action: r.status === 'recapture' ? 'retake' : 'done', message: r.message, tree_id: r.tree_id, observation_id: null,
    model: 'delta', model_name: 'Model Delta (on this phone)', species_checked: true,
    species: sp ? {
      label: sp.label, name: speciesName(sp.label),
      confidence: sp.confidence, hemlock_probability: scores?.hemlock ?? (sp.label === 'tsuga_canadensis' ? sp.confidence : null), top: scores?.top ?? [],
    } : null,
    probability: r.probability, next_view: null,
    candidates: r.candidates.map((c) => ({ tree_id: c.tree_id, probability: c.probability, global_score: c.global })),
    best_guess: r.best_guess ? { ...r.best_guess, note: `Best guess ${r.best_guess.tree_id} (${Math.round(r.best_guess.probability * 100)}%)` } : null,
  };
}

const matchesFrom = (r: api.IdentifyResult, trees: TreeRow[]) => {
  const byId = new Map(trees.map((t) => [t.id, t]));
  return r.candidates
    .filter((c) => byId.has(c.tree_id))
    .map((c) => ({ tree: byId.get(c.tree_id)!, score: c.probability ?? c.global_score ?? 0 }));
};

// Location is a nice-to-have: never wait more than 5 s for the permission prompt or a GPS fix.
export const quickFix = () => Promise.race([fixInForest(), new Promise<null>((r) => setTimeout(() => r(null), 5000))]);

// Where the photos were taken, if location is allowed and the phone is actually in this forest
// (so a demo at home does not put a tree 100 km away on the forest map).
async function fixInForest(): Promise<api.Location | null> {
  const forest = useSession.getState().forest;
  try {
    if (!(await Location.requestForegroundPermissionsAsync()).granted) return null;
    const fix = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    const { latitude: lat, longitude: lon, accuracy } = fix.coords;
    if (forest?.lat != null && forest.lng != null && km(lat, lon, forest.lat, forest.lng) > 25) return null;
    return { lat, lon, accuracy_m: accuracy };
  } catch {
    return null;
  }
}

const km = (a: number, b: number, c: number, d: number) =>
  Math.hypot((a - c) * 111.32, (b - d) * 111.32 * Math.cos((a * Math.PI) / 180));

// Where the phone is now (for a new forest's center), or null within 8 s.
export const hereNow = () => Promise.race([
  (async (): Promise<api.Location | null> => {
    try {
      if (!(await Location.requestForegroundPermissionsAsync()).granted) return null;
      const { latitude: lat, longitude: lon, accuracy } = (await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })).coords;
      return { lat, lon, accuracy_m: accuracy };
    } catch {
      return null;
    }
  })(),
  new Promise<null>((r) => setTimeout(() => r(null), 8000)),
]);
