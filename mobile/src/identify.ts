import * as Location from 'expo-location';
import * as api from './api';
import type { TreeRow } from './data';
import { isServer, useSession } from './session';

export type Match = { tree: TreeRow; score: number };
// `server` is set when hemlock-api ran the model: its decision, the stored visit and the species check.
export type Identification = { matches: Match[]; server?: api.IdentifyResult };

// Offline demo only: cosine similarity a match must clear; below it the photos are treated as a new tree.
// (Signed in, the server decides with its calibrated threshold.)
export const MATCH_THRESHOLD = 0.6;

export async function identify(photos: string[], trees: TreeRow[]): Promise<Identification> {
  if (isServer()) {
    // Location is a nice-to-have: never wait more than 5 s for the permission prompt or a GPS fix.
    const loc = await Promise.race([fixInForest(), new Promise<null>((r) => setTimeout(() => r(null), 5000))]);
    const r = await api.identify(photos, loc);
    const byId = new Map(trees.map((t) => [t.id, t]));
    const matches = r.candidates
      .filter((c) => byId.has(c.tree_id))
      .map((c) => ({ tree: byId.get(c.tree_id)!, score: c.probability ?? c.global_score ?? 0 }));
    return { matches, server: r };
  }
  return { matches: await standIn(photos, trees) };
}

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

// Offline demo stand-in for the model: a stable pseudo-random ranking so the flow can be tried without a server.
async function standIn(photos: string[], trees: TreeRow[]): Promise<Match[]> {
  await new Promise((r) => setTimeout(r, 900));
  const seed = photos.join('');
  const score = (id: string) => {
    let h = 0;
    for (const ch of seed + id) h = (h * 31 + ch.charCodeAt(0)) | 0;
    return 0.3 + ((h >>> 0) % 66) / 100; // 0.30 to 0.95
  };
  return trees
    .map((tree) => ({ tree, score: score(tree.id) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);
}
