import * as Location from 'expo-location';
import * as api from './api';
import { useModels } from './models';
import type { TreeRow } from './data';
import { isServer, useSession } from './session';

export type Match = { tree: TreeRow; score: number };
// `server` is set when hemlock-api ran the model: its decision, the stored visit and the species check.
// offline: no model ran (offline demo); matches are the forest's trees, unscored, for a manual pick.
export type Identification = { matches: Match[]; server?: api.IdentifyResult; offline?: boolean };

export async function identify(photos: string[], trees: TreeRow[], done?: api.IdentifyResult | null): Promise<Identification> {
  if (done) return { matches: matchesFrom(done, trees), server: done };
  if (isServer()) {
    const r = await api.identify(photos, await quickFix(), useModels.getState().chosen ?? undefined);
    return { matches: matchesFrom(r, trees), server: r };
  }
  // The model runs on the server. Offline there is no identification: never invent a match score.
  return { matches: trees.map((tree) => ({ tree, score: NaN })), offline: true };
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
