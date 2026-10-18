import type { Bbox, Hotspot, Landmark, Section } from './api';
import { CONDITIONS, likelihoodColor, type Layer } from './conditions';
import type { TreeRow } from './data';
import { status } from './theme';

export type MapProps = {
  trees: TreeRow[];
  landmarks: Landmark[];
  sections: Section[]; // drawn when showSections
  showSections: boolean;
  hotspots: Hotspot[]; // for the current condition layer
  layer: Layer;
  selected?: string;
  onSelect(id: string): void;
  onView(bbox: Bbox): void; // visible area, for "Analyze this view"
};

export const pinColor = (t: TreeRow, layer: Layer) =>
  layer === 'health' ? status[t.status ?? 'unrated'].dot : likelihoodColor(layer, t.conditions?.[layer]);

export const hotspotColor = (layer: Layer) => (layer === 'health' ? '#A3442F' : CONDITIONS[layer].color);

export const LANDMARK_STYLE = {
  stream: { color: '#3E7CB1', width: 3 },
  ridge: { color: '#8B6F4E', width: 2 },
  trail: { color: '#7A5C3E', width: 1.5 },
  road: { color: '#9A8F7E', width: 3 },
} as const;
