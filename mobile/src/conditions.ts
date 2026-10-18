import type { ConditionKey } from './api';

// The three conditions the backend assesses (docs/research/hemlock_health.md), with map colors.
export const CONDITIONS: Record<ConditionKey, { short: string; tiny: string; name: string; color: string; tint: string }> = {
  hwa: { short: 'Woolly adelgid', tiny: 'HWA', name: 'Hemlock woolly adelgid (HWA)', color: '#7B4FA0', tint: '#EDE4F4' },
  ehs: { short: 'Hemlock scale', tiny: 'scale', name: 'Elongate hemlock scale (EHS)', color: '#B5602A', tint: '#F6E6DA' },
  drought_stress: { short: 'Drought stress', tiny: 'drought', name: 'Drought stress and secondary decline', color: '#B8931A', tint: '#F5EDD2' },
};
export const CONDITION_KEYS = Object.keys(CONDITIONS) as ConditionKey[];

// Map layers: tree health (severity), or how likely each tree has one condition.
export type Layer = 'health' | ConditionKey;

// Pin color for a likelihood 0-1 on a condition layer: grey when unlikely, full color when likely.
export function likelihoodColor(c: ConditionKey, p: number | undefined) {
  if (p == null) return '#B9BFB9';
  if (p >= 0.6) return CONDITIONS[c].color;
  if (p >= 0.35) return CONDITIONS[c].color + 'AA';
  return '#C9D1C8';
}
