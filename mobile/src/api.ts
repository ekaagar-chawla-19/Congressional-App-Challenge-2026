import Constants from 'expo-constants';
import { Platform } from 'react-native';
import { useSession, type User } from './session';

// Client for hemlock-api (the Python backend in this repo, /api/v1). Only the calls the app uses.

export type Location = { lat: number; lon: number; accuracy_m?: number | null };
export type Sensors = { soil_moisture_pct: number | null; air_temp_c: number | null; humidity_pct: number | null; light_lux: number | null };
export type Finding = { condition: string; name: string; likelihood: number; level: 'likely' | 'possible' | 'low' | 'unknown'; evidence: string[] };
export type ForestSummary = {
  forest_id: number; name: string; center: Location | null; tree_count: number; observation_count: number;
  severity_counts: Record<'none' | 'light' | 'moderate' | 'severe' | 'unrated', number>; last_visit_at: string | null;
};
export type TreeSummary = {
  tree_id: string; species: string; name: string; main_condition: string | null; severity: number | null;
  location: Location | null; created_at: string; last_seen_at: string; observation_count: number;
  notes: string | null; thumbnail_url: string | null;
};
export type Observation = {
  observation_id: string; severity: number | null; health_notes: string | null; has_photos: boolean;
  sensors: Sensors | null; signs: string[]; findings: Finding[]; tree_id: string | null; timestamp: string;
  status: string; location: Location | null; views: { view_index: number; view_type: string; image_url: string | null }[];
};
export type TreeDetail = TreeSummary & { current_conditions: Finding[]; latest_sensors: Sensors | null; observations: Observation[] };
export type Candidate = { tree_id: string; probability: number | null; global_score: number | null };
export type IdentifyResult = {
  status: 'existing' | 'new' | 'uncertain' | 'recapture' | 'rejected_species' | 'unsupported_species' | string;
  action: string; message: string; tree_id: string | null; observation_id: string | null;
  species: { label: string; name: string; confidence: number } | null; probability: number | null;
  candidates: Candidate[]; best_guess: { tree_id: string; probability: number | null; note: string } | null;
};

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

// hemlock-api runs on the same computer as the Expo dev server, on port 8000.
export function defaultServer() {
  if (process.env.EXPO_PUBLIC_API_URL) return process.env.EXPO_PUBLIC_API_URL.replace(/\/$/, '');
  const host = Platform.OS === 'web' ? globalThis.location?.hostname : Constants.expoConfig?.hostUri?.split(':')[0];
  return `http://${host || 'localhost'}:8000`;
}

type Opts = { method?: string; json?: unknown; form?: FormData; server?: string; timeout?: number };

async function request<T>(path: string, o: Opts = {}): Promise<T> {
  const { server, token, forest } = useSession.getState();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (forest) headers['X-Forest-Id'] = String(forest.id);
  if (o.json !== undefined) headers['Content-Type'] = 'application/json';
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), o.timeout ?? 15_000);
  let res: Response;
  try {
    res = await fetch(`${o.server ?? server}/api/v1${path}`, {
      method: o.method ?? (o.json !== undefined || o.form ? 'POST' : 'GET'),
      headers,
      body: o.form ?? (o.json !== undefined ? JSON.stringify(o.json) : undefined),
      signal: ctl.signal,
    });
  } catch {
    throw new ApiError(0, 'offline', `Can't reach the HemlockID server at ${o.server ?? server}.`);
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) useSession.getState().signOut(); // expired session: back to sign-in
    throw new ApiError(res.status, body?.error?.code ?? 'http_error', body?.error?.message ?? `Server error ${res.status}`);
  }
  return body as T;
}

export const login = (server: string, email: string, password: string) =>
  request<{ token: string; user: User & { user_id: number } }>('/auth/login', { server, json: { email, password } });
export const logout = () => request<void>('/auth/logout', { method: 'POST', timeout: 3000 });

export const forests = () => request<ForestSummary[]>('/forests');
export const trees = () => request<{ items: TreeSummary[] }>('/trees?limit=500').then((p) => p.items);
export const tree = (id: string) => request<TreeDetail>(`/trees/${encodeURIComponent(id)}`);

// Sends 3-5 bark photos; the server runs the model, stores the visit and answers which tree it is.
export async function identify(photos: string[], loc: Location | null) {
  const form = new FormData();
  for (const [i, uri] of photos.entries()) {
    if (Platform.OS === 'web') form.append('images', await (await fetch(uri)).blob(), `view${i}.jpg`);
    else form.append('images', { uri, name: `view${i}.jpg`, type: 'image/jpeg' } as unknown as Blob);
  }
  if (loc) {
    form.append('lat', String(loc.lat));
    form.append('lon', String(loc.lon));
    if (loc.accuracy_m != null) form.append('accuracy_m', String(loc.accuracy_m));
  }
  return request<IdentifyResult>('/identify', { form, timeout: 120_000 });
}

export const assign = (observationId: string, treeId: string | 'new') =>
  request<{ tree_id: string; created_tree: boolean }>(`/observations/${observationId}/assign`, { json: { tree_id: treeId } });
export const setSigns = (observationId: string, signs: string[]) =>
  request<Observation>(`/observations/${observationId}/signs`, { method: 'PUT', json: { signs } });
export const setHealth = (observationId: string, severity: number, notes: string) =>
  request<Observation>(`/observations/${observationId}/health`, { method: 'PUT', json: { severity, notes: notes || null } });

// Image URLs from the API are relative and need the sign-in token and forest.
export const absolute = (path: string | null) => (path ? `${useSession.getState().server}${path}` : null);
export const imageSource = (uri: string) => {
  const { server, token, forest } = useSession.getState();
  if (!server || !token || !uri.startsWith(server)) return { uri };
  return { uri, headers: { Authorization: `Bearer ${token}`, 'X-Forest-Id': String(forest?.id ?? '') } };
};
