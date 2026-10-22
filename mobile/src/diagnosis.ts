import type { Finding, Sensors } from './api';

// The backend's diagnosis rules, run on the phone so the phone-only mode gives the same answers without a
// computer. Line-for-line port of src/hemlock_sentinel/api/diseases.py (assess) and api/twin.py; checked
// against the Python on random visits by tests/integration/test_phone_diagnosis.py. Keep the two in step.

// The server's condition names (diseases.py), used in findings and "since last visit" lines.
export const NAMES: Record<string, string> = {
  hwa: 'Hemlock woolly adelgid (HWA)',
  ehs: 'Elongate hemlock scale (EHS)',
  drought_stress: 'Drought stress and secondary decline (root rot, borers)',
};

export const T = {
  warnSoil: 22, drySoil: 15, hot: 32, highVpd: 1.5, hwaColdKill: -20, lowLight: 1000,
  soilStep: 5, vpdStep: 0.3, tempStep: 3,
} as const;

export const vpdKpa = (t: number, rh: number) => 0.6108 * Math.exp((17.27 * t) / (t + 237.3)) * (1 - rh / 100);
const level = (p: number): Finding['level'] => (p >= 0.7 ? 'likely' : p >= 0.35 ? 'possible' : 'low');
const r2 = (x: number) => Math.round(x * 100) / 100;
// Python's "{x:.0f}" rounds half to even; so does this for the values that matter here.
const f0 = (x: number) => {
  const r = Math.round(x);
  return String(Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r);
};
const pct0 = (x: number) => `${f0(x * 100)}%`;
const f1 = (x: number) => {
  // Python rounds by the exact stored value, ties to even. toFixed also uses the exact value but rounds ties
  // up, so only a true tie (the double is exactly n.n5, e.g. 1.25 but not 0.45) needs the even rule.
  const exact = Math.abs(x).toFixed(30);
  const tie = /\.\d50+$/.test(exact);
  if (!tie) return x.toFixed(1);
  const t = Math.round(x * 10);
  return ((t % 2 === 0 ? t : t - Math.sign(x)) / 10).toFixed(1);
};

type Out = Omit<Finding, 'name'>;
export type Ai = Partial<Record<'hwa_wool' | 'ehs_scale' | 'needle_yellow_banding', number>>;

/** Per-condition findings for one visit (diseases.assess). when: ms since epoch. */
export function assess(signs: string[] | null, sensors: Partial<Sensors> | null, severity: number | null = null,
  when: number | null = null, hasImages = false, ai: Ai | null = null): Finding[] {
  const s = new Set(signs ?? []);
  const sn = sensors ?? {};
  const a = ai ?? {};
  const month = when != null ? new Date(when).getUTCMonth() + 1 : null;
  const summer = month != null && month >= 6 && month <= 9;
  const decline = ['gray_green_foliage', 'needle_loss', 'no_new_growth', 'branch_dieback'].filter((k) => s.has(k)).length;
  const t = sn.air_temp_c ?? null, hum = sn.humidity_pct ?? null, soil = sn.soil_moisture_pct ?? null;
  const twigsSeen = ['hwa_wool', 'ehs_scale', 'twigs_checked_clean'].some((k) => s.has(k)) || Object.keys(a).length > 0;
  const out: Out[] = [];
  const add = (condition: string, p: number, evidence: string[]) => out.push({ condition, likelihood: r2(p), level: level(p), evidence });
  const unknown = (condition: string, why: string) => out.push({ condition, likelihood: 0, level: 'unknown', evidence: [why] });

  // HWA
  let ev: string[] = [], p = 0;
  if (s.has('hwa_wool')) {
    p = 0.9; ev = ['observed: white wool at needle bases (diagnostic sign)'];
    if (severity != null && severity >= 2) { p = 0.95; ev.push(`observer severity rating ${severity}`); }
  } else if ((a.hwa_wool ?? 0) >= 0.3) {
    p = 0.35 + 0.4 * a.hwa_wool!;
    ev.push(`AI photo check suggests wool at needle bases (confidence ${pct0(a.hwa_wool!)}); confirm by eye before treating`);
  } else if (s.has('twigs_checked_clean')) {
    p = summer ? 0.25 : 0.08;
    ev.push('twig undersides checked, no wool found');
    if (summer) ev.push('June-September: wool is sparse during summer dormancy, so a clean check is weak evidence; re-check November-June');
    if (decline) { p += 0.1; ev.push(`crown decline signs (${decline}) present`); }
  } else if (decline) {
    p = 0.2 + 0.08 * decline;
    ev.push(`crown decline signs (${decline}) fit HWA but are not specific; check twig undersides`);
  }
  if (t != null && t <= T.hwaColdKill && p) {
    p = Math.max(0.05, p - 0.15);
    ev.push(`reading of ${f0(t)} °C: cold this severe kills many adelgids`);
  }
  if (p) add('hwa', p, ev);
  else if (!twigsSeen) unknown('hwa', 'not assessed: needs a check of twig undersides' + (hasImages ? ' (trunk-bark photos cannot show HWA)' : ''));

  // EHS
  ev = []; p = 0;
  if (s.has('ehs_scale')) {
    p = 0.85; ev = ['observed: scale covers on needle undersides (diagnostic sign)'];
    if (s.has('needle_yellow_banding')) { p = 0.92; ev.push('observed: yellow banding on needle tops'); }
  } else if ((a.ehs_scale ?? 0) >= 0.3) {
    p = 0.3 + 0.4 * a.ehs_scale!;
    ev = [`AI photo check suggests scale covers (confidence ${pct0(a.ehs_scale!)}); confirm with a hand lens`];
  } else if (s.has('needle_yellow_banding') || (a.needle_yellow_banding ?? 0) >= 0.5) {
    p = 0.4; ev = ['yellow banding is typical of EHS; confirm by finding scales on needle undersides'];
  } else if (s.has('twigs_checked_clean')) {
    p = 0.08; ev = ['needle undersides checked, no scales found'];
  }
  if (p) add('ehs', p, ev);
  else if (!twigsSeen) unknown('ehs', 'not assessed: needs a check of needle undersides');

  // Drought stress
  ev = []; p = 0;
  if (soil != null) {
    if (soil < T.drySoil) { p += 0.45; ev.push(`soil moisture ${f0(soil)}% (dry, below ${f0(T.drySoil)}%)`); }
    else if (soil < T.warnSoil) { p += 0.2; ev.push(`soil moisture ${f0(soil)}% (getting dry)`); }
  }
  if (t != null && hum != null) {
    const v = vpdKpa(t, hum);
    if (v >= T.highVpd) { p += 0.15; ev.push(`high evaporative demand (VPD ${f1(v)} kPa from ${f0(t)} °C, ${f0(hum)}% RH)`); }
  } else if (t != null && t >= T.hot) {
    p += 0.1; ev.push(`air temperature ${f0(t)} °C`);
  }
  if (s.has('drought_browning')) { p += 0.3; ev.push('observed: browning/wilting during a dry spell'); }
  for (const [k, txt] of [['borer_holes', 'borer exit holes in bark'], ['root_rot_signs', 'root-rot signs at the base']] as const) {
    if (s.has(k)) { p += 0.3; ev.push(`observed: ${txt} (secondary attackers of stressed trees)`); }
  }
  if (p && decline && s.has('twigs_checked_clean')) { p += 0.1; ev.push('crown decline without insects on the twigs points to abiotic stress'); }
  if (p) add('drought_stress', Math.min(0.9, p), ev);
  else if (soil != null) add('drought_stress', 0.05, [`soil moisture ${f0(soil)}% (not dry)`]);
  else if (!['drought_browning', 'borer_holes', 'root_rot_signs'].some((k) => s.has(k)))
    unknown('drought_stress', 'not assessed: no soil-moisture reading or stress signs recorded');

  const lux = sn.light_lux ?? null;
  if (lux != null && lux < T.lowLight) {
    for (const f of out) if (f.level !== 'unknown') f.evidence.push(`low light at the visit (${f0(lux)} lux): small signs are easy to miss`);
  }
  // Python's sorted() is stable: equal likelihoods keep their order
  return out.map((f, i) => [f, i] as const).sort((x, y) => y[0].likelihood - x[0].likelihood || x[1] - y[1])
    .map(([f]) => ({ ...f, name: NAMES[f.condition] ?? f.condition }));
}

// ------------------------------------------------------------------ twin.py
export type Visit = { id: string; at: number; severity: number | null; signs: string[]; sensors: Sensors | null; findings: Finding[] };
export type SensorPoint = { observation_id: string; timestamp: string; sensors: Sensors; vpd_kpa: number | null };
export type Environment = { summary: string; vpd_kpa: number | null; water_stress: 'low' | 'some' | 'high'; changes: string[] };

const SEVERITY: Record<number, string> = { 0: 'healthy', 1: 'light decline', 2: 'moderate decline', 3: 'severe decline' };
const vpdOf = (s: Sensors) => (s.air_temp_c != null && s.humidity_pct != null ? r2(vpdKpa(s.air_temp_c, s.humidity_pct)) : null);

/** Every visit with a reading, newest first. visits: oldest first. */
export function sensorHistory(visits: Visit[]): SensorPoint[] {
  return [...visits].reverse().filter((v) => v.sensors && Object.values(v.sensors).some((x) => x != null))
    .map((v) => ({ observation_id: v.id, timestamp: new Date(v.at).toISOString(), sensors: v.sensors!, vpd_kpa: vpdOf(v.sensors!) }));
}

export function environment(history: SensorPoint[]): Environment | null {
  if (!history.length) return null;
  const s = history[0].sensors, vpd = history[0].vpd_kpa;
  const soil = s.soil_moisture_pct, lux = s.light_lux;
  const parts: string[] = [];
  if (soil != null) parts.push(soil < T.drySoil ? 'dry soil' : soil < T.warnSoil ? 'soil getting dry' : 'moist soil');
  if (vpd != null) parts.push(vpd >= T.highVpd ? 'thirsty air' : 'mild air');
  if (lux != null && lux < T.lowLight) parts.push('low light');
  const stress = Number(soil != null && soil < T.warnSoil) + Number(vpd != null && vpd >= T.highVpd);
  const verdict = ['Low water stress', 'Some water stress', 'High water stress'][stress];
  const summary = parts.length ? `${verdict}: ${parts.join(', ')}.` : 'Only a partial reading.';
  const changes: string[] = [];
  if (history.length >= 2) {
    const p = history[1].sensors, pv = history[1].vpd_kpa;
    if (soil != null && p.soil_moisture_pct != null) {
      const d = soil - p.soil_moisture_pct;
      if (Math.abs(d) >= T.soilStep) changes.push(`Soil ${d > 0 ? 'wetter' : 'drier'} by ${f0(Math.abs(d))} points`);
    }
    if (vpd != null && pv != null && Math.abs(vpd - pv) >= T.vpdStep) changes.push(`Air ${vpd > pv ? 'thirstier' : 'calmer'} (VPD ${f1(pv)} → ${f1(vpd)} kPa)`);
    const t = s.air_temp_c, pt = p.air_temp_c;
    if (t != null && pt != null && Math.abs(t - pt) >= T.tempStep) changes.push(`${f0(Math.abs(t - pt))} °C ${t > pt ? 'warmer' : 'cooler'}`);
    if (!changes.length) changes.push('Conditions about the same as last reading');
  }
  return { summary, vpd_kpa: vpd, water_stress: (['low', 'some', 'high'] as const)[stress], changes };
}

const known = (v: Visit) => Object.fromEntries(v.findings.filter((f) => f.level !== 'unknown').map((f) => [f.condition, f.likelihood]));

export function sinceLastVisit(visits: Visit[]): string[] {
  const assessed = visits.filter((v) => v.severity != null || Object.keys(known(v)).length || v.sensors);
  if (assessed.length < 2) return [];
  const [a, b] = assessed.slice(-2);
  const out: string[] = [];
  if (a.severity != null && b.severity != null && a.severity !== b.severity)
    out.push(`Health ${b.severity > a.severity ? 'worse' : 'better'}: ${SEVERITY[a.severity]} → ${SEVERITY[b.severity]}`);
  const ka = known(a), kb = known(b);
  for (const c of Object.keys(NAMES)) {
    if (c in ka && c in kb && Math.abs(kb[c] - ka[c]) >= 0.15)
      out.push(`${NAMES[c]} ${kb[c] > ka[c] ? 'more' : 'less'} likely (${pct0(ka[c])} → ${pct0(kb[c])})`);
  }
  const fresh = new Set(b.signs.filter((x) => !a.signs.includes(x) && x !== 'twigs_checked_clean'));
  if (fresh.size) out.push(`${fresh.size} new sign${fresh.size > 1 ? 's' : ''} recorded`);
  return out.length ? out : ['No change in health since the last visit'];
}

/** withUnit: suggest a sensor reading only to people who have a sensor unit (the hardware is optional). */
export function nextAction(visits: Visit[], current: Finding[], env: Environment | null, withUnit = true): string {
  const likely = current.filter((f) => f.level === 'likely');
  if (likely.some((f) => f.condition === 'hwa')) return 'Report the adelgid and plan treatment with a licensed applicator.';
  if (likely.some((f) => f.condition === 'ehs')) return 'Confirm the scale with a hand lens, then plan treatment.';
  if (current.some((f) => f.level === 'unknown' && (f.condition === 'hwa' || f.condition === 'ehs'))) return 'Check the undersides of a few twigs for wool or scale.';
  if (current.some((f) => f.condition === 'drought_stress' && (f.level === 'likely' || f.level === 'possible'))) return 'Water stress: re-check soil moisture after the next dry week.';
  if (env == null && withUnit) return 'Take an ESP32 reading on the next visit.';
  if (visits.length && visits[visits.length - 1].severity == null) return 'Rate the crown on the next visit.';
  return 'Re-scan in about 3 months to keep its history going.';
}

/** The latest assessed finding per condition (analysis.tree_profiles), over visits oldest first. */
export function currentConditions(visits: Visit[]): Finding[] {
  const cur: Record<string, Finding> = {};
  for (const v of visits) for (const f of v.findings) if (f.level !== 'unknown') cur[f.condition] = f;
  return Object.values(cur).sort((a, b) => b.likelihood - a.likelihood);
}
