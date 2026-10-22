import type { ConditionKey, Sensors } from './api';

// The three conditions the backend assesses (docs/research/hemlock_health.md), with map colors.
export const CONDITIONS: Record<ConditionKey, { short: string; tiny: string; name: string; color: string; tint: string }> = {
  hwa: { short: 'Woolly adelgid', tiny: 'HWA', name: 'Hemlock woolly adelgid (HWA)', color: '#7B4FA0', tint: '#EDE4F4' },
  ehs: { short: 'Hemlock scale', tiny: 'scale', name: 'Elongate hemlock scale (EHS)', color: '#B5602A', tint: '#F6E6DA' },
  drought_stress: { short: 'Drought stress', tiny: 'drought', name: 'Drought stress and secondary decline', color: '#B8931A', tint: '#F5EDD2' },
};
export const CONDITION_KEYS = Object.keys(CONDITIONS) as ConditionKey[];

// Map layers: tree health (severity), how likely each tree has one condition, or one sensor's latest reading.
export type SensorLayer = 'soil' | 'temp' | 'humidity' | 'light';
export type Layer = 'health' | ConditionKey | SensorLayer;

// Sensor layers: each tree colored by its latest reading, in bands that match the diagnosis thresholds
// (dry soil < 15 %, getting dry < 22 %, hot >= 32 °C, dry air < 40 % RH, too dark < 1000 lux).
export const SENSOR_LAYERS: Record<SensorLayer, { key: keyof Sensors; label: string; bands: { below: number; color: string; label: string }[] }> = {
  soil: { key: 'soil_moisture_pct', label: 'Soil', bands: [
    { below: 15, color: '#A3442F', label: 'Dry' }, { below: 22, color: '#C08A2E', label: 'Getting dry' }, { below: Infinity, color: '#3E7CB1', label: 'Moist' }] },
  temp: { key: 'air_temp_c', label: 'Temp', bands: [
    { below: 10, color: '#3E7CB1', label: 'Cool' }, { below: 32, color: '#5E7D5A', label: 'Mild' }, { below: Infinity, color: '#A3442F', label: 'Hot' }] },
  humidity: { key: 'humidity_pct', label: 'Humidity', bands: [
    { below: 40, color: '#C08A2E', label: 'Dry air' }, { below: 75, color: '#5E7D5A', label: 'Normal' }, { below: Infinity, color: '#3E7CB1', label: 'Humid' }] },
  light: { key: 'light_lux', label: 'Light', bands: [
    { below: 1000, color: '#4A3D33', label: 'Too dark' }, { below: Infinity, color: '#E0B15A', label: 'Bright enough' }] },
};
export const isSensorLayer = (l: Layer): l is SensorLayer => l in SENSOR_LAYERS;
export const NO_READING = '#B9BFB9';

export function sensorColor(l: SensorLayer, v: number | null | undefined) {
  if (v == null) return NO_READING;
  return SENSOR_LAYERS[l].bands.find((b) => v < b.below)!.color;
}

// Pin color for a likelihood 0-1 on a condition layer: grey when unlikely, full color when likely.
export function likelihoodColor(c: ConditionKey, p: number | undefined) {
  if (p == null) return '#B9BFB9';
  if (p >= 0.6) return CONDITIONS[c].color;
  if (p >= 0.35) return CONDITIONS[c].color + 'AA';
  return '#C9D1C8';
}
