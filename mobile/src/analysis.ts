import type { Analysis, Bbox, ConditionKey, Finding, Hotspot, Section, Sensors, Trend } from './api';
import type { Visit } from './diagnosis';
import guide from './conditionGuide';

// Forest, section and map-area analysis on the phone, so Insights works in phone-only mode. Port of
// src/hemlock_sentinel/api/analysis.py (tree_profiles, summarize, stress_score, zones, hotspots, trends) and
// server.analysis_for / section_out; checked against the Python by tests/integration/test_phone_analysis.py.
// conditionGuide.ts is diseases.CONDITIONS' advice text, also checked by that test.

const KEYS: ConditionKey[] = ['hwa', 'ehs', 'drought_stress'];
const SENSOR_FIELDS: (keyof Sensors)[] = ['soil_moisture_pct', 'air_temp_c', 'humidity_pct', 'light_lux'];
const SEVERITY = ['none', 'light', 'moderate', 'severe'];

/** Python's round(x, n): the exact double, ties to even (toFixed is exact too but rounds ties away from zero). */
export function pyRound(x: number, n: number): number {
  const exact = Math.abs(x).toFixed(100);
  const dot = exact.indexOf('.');
  const tail = exact.slice(dot + 1 + n);
  if (!/^50*$/.test(tail)) return Number(x.toFixed(n));
  const scaled = Math.trunc(Math.abs(x) * 10 ** n + 0.25); // the digits kept (|x| = scaled.5 at this scale)
  const kept = scaled % 2 === 0 ? scaled : scaled + 1;
  return (Math.sign(x) * kept) / 10 ** n;
}

export type TreeInput = { id: string; lat: number | null; lon: number | null; visits: Visit[] }; // visits oldest first
type Cond = Finding & { timestamp: number };
export type Profile = {
  tree_id: string; lat: number | null; lon: number | null; severity: number | null;
  conditions: Record<string, Cond>; latest_sensors: Sensors | null; visits: number; main_condition: ConditionKey | null;
};

/** Per tree: location, latest severity, latest reading, the latest assessed finding per condition. */
export function treeProfiles(trees: TreeInput[]): Profile[] {
  const withVisits = trees.filter((t) => t.visits.length).sort((a, b) => a.visits[0].at - b.visits[0].at);
  return withVisits.map((t) => {
    const p: Profile = { tree_id: t.id, lat: t.lat, lon: t.lon, severity: null, conditions: {}, latest_sensors: null, visits: 0, main_condition: null };
    for (const v of t.visits) {
      p.visits++;
      if (v.severity != null) p.severity = v.severity;
      if (v.sensors) p.latest_sensors = v.sensors;
      for (const f of v.findings) if (f.level !== 'unknown') p.conditions[f.condition] = { ...f, timestamp: v.at };
    }
    let main: Cond | null = null;
    for (const f of Object.values(p.conditions)) if (!main || f.likelihood > main.likelihood) main = f;
    p.main_condition = main && main.likelihood >= 0.35 ? (main.condition as ConditionKey) : null;
    return p;
  });
}

export function summarize(profiles: Profile[]): Analysis['summary'] {
  const sev = profiles.map((p) => p.severity).filter((s): s is number => s != null);
  const cond = Object.fromEntries(KEYS.map((c) => [c, { likely: 0, possible: 0, assessed: 0 }])) as Record<ConditionKey, { likely: number; possible: number; assessed: number }>;
  for (const p of profiles) {
    for (const [c, f] of Object.entries(p.conditions)) {
      const k = cond[c as ConditionKey];
      if (!k) continue;
      k.assessed++;
      if (f.level === 'likely' || f.level === 'possible') k[f.level]++;
    }
  }
  const sensor_means: Analysis['summary']['sensor_means'] = {};
  for (const k of SENSOR_FIELDS) {
    const vals = profiles.map((p) => p.latest_sensors?.[k]).filter((v): v is number => v != null);
    sensor_means[k] = vals.length ? { mean: pyRound(vals.reduce((a, b) => a + b, 0) / vals.length, 1), n: vals.length } : null;
  }
  const counts = Object.fromEntries(KEYS.map((c) => [c, cond[c].likely + cond[c].possible])) as Record<ConditionKey, number>;
  let prominent: ConditionKey | null = null;
  for (const c of KEYS) if (counts[c] && (prominent == null || counts[c] > counts[prominent])) prominent = c;
  const severity_counts: Record<string, number> = { none: 0, light: 0, moderate: 0, severe: 0, unrated: 0 };
  for (const p of profiles) severity_counts[p.severity != null ? SEVERITY[p.severity] ?? 'unrated' : 'unrated']++;
  const C = guide.conditions as Record<ConditionKey, { name: string; recommendations: string[]; confirm: string }>;
  return {
    trees: profiles.length,
    severity_counts,
    mean_severity: sev.length ? pyRound(sev.reduce((a, b) => a + b, 0) / sev.length, 2) : null,
    pct_moderate_or_severe: sev.length ? pyRound((100 * sev.filter((s) => s >= 2).length) / sev.length, 1) : null,
    conditions: Object.fromEntries(KEYS.map((c) => [c, { ...cond[c], name: C[c].name }])) as Analysis['summary']['conditions'],
    most_prominent_condition: prominent,
    sensor_means,
    trees_with_sensor_data: profiles.filter((p) => p.latest_sensors).length,
    recommendations: KEYS.map((c) => [c, counts[c]] as const).sort((a, b) => b[1] - a[1]).filter(([, n]) => n)
      .map(([c, n]) => ({ condition: c, name: C[c].name, trees_affected: n, steps: C[c].recommendations, how_to_confirm: C[c].confirm })),
    general_advice: guide.general_advice,
  };
}

export const inBbox = (p: Profile, [w, s, e, n]: Bbox) => p.lat != null && p.lon != null && s <= p.lat && p.lat <= n && w <= p.lon && p.lon <= e;

/** 0-1 ranking score: severity plus the worst likelihood of any condition. */
export function stressScore(p: Profile): number {
  const sev = (p.severity ?? 0) / 3;
  const worst = Math.max(0, ...Object.values(p.conditions).map((f) => f.likelihood));
  return pyRound(0.6 * sev + 0.4 * worst, 3);
}

type Zone = Hotspot & { stress_score: number; condition_counts: Record<ConditionKey, number> };

/** Square grid over the located trees; cells ranked worst first. */
export function zones(profiles: Profile[], cellM = 150): Zone[] {
  const pts = profiles.filter((p) => p.lat != null);
  if (!pts.length) return [];
  const lat0 = Math.min(...pts.map((p) => p.lat!)), lon0 = Math.min(...pts.map((p) => p.lon!));
  const dlat = cellM / 111_320, dlon = cellM / (111_320 * Math.cos(lat0 * (Math.PI / 180)));
  const cells = new Map<string, { i: number; j: number; ps: Profile[] }>();
  for (const p of pts) {
    const i = Math.trunc((p.lat! - lat0) / dlat), j = Math.trunc((p.lon! - lon0) / dlon);
    const c = cells.get(`${i}-${j}`) ?? cells.set(`${i}-${j}`, { i, j, ps: [] }).get(`${i}-${j}`)!;
    c.ps.push(p);
  }
  const out: Zone[] = [...cells.values()].map(({ i, j, ps }) => {
    const s = lat0 + i * dlat, w = lon0 + j * dlon;
    const summ = summarize(ps);
    return {
      zone_id: `${i}-${j}`, bbox: [pyRound(w, 6), pyRound(s, 6), pyRound(w + dlon, 6), pyRound(s + dlat, 6)],
      center: { lat: pyRound(s + dlat / 2, 6), lon: pyRound(w + dlon / 2, 6) },
      stress_score: pyRound(ps.reduce((a, p) => a + stressScore(p), 0) / ps.length, 3),
      tree_ids: ps.map((p) => p.tree_id).sort(), trees: summ.trees, affected: 0, share: 0,
      condition_counts: Object.fromEntries(KEYS.map((c) => [c, summ.conditions[c].likely + summ.conditions[c].possible])) as Record<ConditionKey, number>,
    };
  });
  return out.sort((a, b) => b.stress_score - a.stress_score || b.trees - a.trees);
}

/** Per condition: the cells where the most trees show it, worst first. */
export function hotspots(profiles: Profile[], cellM = 150, top = 3): Record<ConditionKey, Hotspot[]> {
  const out = Object.fromEntries(KEYS.map((c) => [c, [] as Hotspot[]])) as Record<ConditionKey, Hotspot[]>;
  for (const z of zones(profiles, cellM)) {
    for (const c of KEYS) {
      const n = z.condition_counts[c];
      if (n) out[c].push({ zone_id: z.zone_id, bbox: z.bbox, center: z.center, trees: z.trees, affected: n, share: pyRound(n / z.trees, 3), tree_ids: z.tree_ids });
    }
  }
  for (const c of KEYS) out[c] = out[c].sort((a, b) => b.affected - a.affected || b.share - a.share).slice(0, top);
  return out;
}

const period = (ms: number) => {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
};

/** Per quarter, over the visits made in it: severity, share moderate/severe, share of assessed visits per condition. */
export function trends(trees: TreeInput[], ids: Set<string>): Trend[] {
  const rows = trees.filter((t) => ids.has(t.id)).flatMap((t) => t.visits.map((v) => ({ tree: t.id, v })))
    .sort((a, b) => a.v.at - b.v.at);
  const buckets = new Map<string, { visits: number; trees: Set<string>; sev: number[]; cond: Record<string, [number, number]> }>();
  for (const { tree, v } of rows) {
    const k = period(v.at);
    const b = buckets.get(k) ?? buckets.set(k, { visits: 0, trees: new Set(), sev: [], cond: Object.fromEntries(KEYS.map((c) => [c, [0, 0]])) }).get(k)!;
    b.visits++;
    b.trees.add(tree);
    if (v.severity != null) b.sev.push(v.severity);
    for (const f of v.findings) {
      if (f.level !== 'unknown' && b.cond[f.condition]) {
        b.cond[f.condition][1]++;
        if (f.level === 'likely' || f.level === 'possible') b.cond[f.condition][0]++;
      }
    }
  }
  return [...buckets.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, b]) => ({
    period: k, visits: b.visits, trees: b.trees.size,
    mean_severity: b.sev.length ? pyRound(b.sev.reduce((x, y) => x + y, 0) / b.sev.length, 2) : null,
    pct_moderate_or_severe: b.sev.length ? pyRound((100 * b.sev.filter((x) => x >= 2).length) / b.sev.length, 1) : null,
    conditions: Object.fromEntries(KEYS.map((c) => {
      const [a, n] = b.cond[c];
      return [c, { pct: n ? pyRound((100 * a) / n, 1) : null, assessed: n }];
    })) as Trend['conditions'],
  }));
}

export type SavedSection = { section_id: number; name: string; bbox: Bbox };

export function sectionOut(sec: SavedSection, profiles: Profile[]): Section {
  const ps = profiles.filter((p) => inBbox(p, sec.bbox));
  const summ = summarize(ps);
  return {
    section_id: sec.section_id, name: sec.name, bbox: sec.bbox, trees: summ.trees, mean_severity: summ.mean_severity,
    pct_moderate_or_severe: summ.pct_moderate_or_severe, most_prominent_condition: summ.most_prominent_condition,
    stress_score: ps.length ? pyRound(ps.reduce((a, p) => a + stressScore(p), 0) / ps.length, 3) : null,
    condition_counts: Object.fromEntries(KEYS.map((c) => [c, summ.conditions[c].likely + summ.conditions[c].possible])) as Record<ConditionKey, number>,
  };
}

/** The whole forest, or the trees inside bbox (sections are listed for the whole forest only). */
export function analyze(trees: TreeInput[], sections: SavedSection[], bbox?: Bbox | null, cellM = 150): Analysis {
  const all = treeProfiles(trees);
  const profs = bbox ? all.filter((p) => inBbox(p, bbox)) : all;
  return {
    area: bbox ? { west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] } : null,
    summary: summarize(profs),
    hotspots: hotspots(profs, cellM),
    trends: trends(trees, new Set(profs.map((p) => p.tree_id))),
    sections: bbox ? [] : sections.map((s) => sectionOut(s, all)),
    worst_trees: [...profs].sort((a, b) => stressScore(b) - stressScore(a)).slice(0, 10)
      .map((p) => ({ tree_id: p.tree_id, stress_score: stressScore(p), severity: p.severity, main_condition: p.main_condition })),
  };
}
