import { create } from 'zustand';
import * as api from './api';
import Storage from './kv';

// Which re-ID model scans use. The server runs the models (GET /models lists them); the app only chooses.
// The last choice is remembered on this phone and preselected the next time the picker opens.
const KEY = 'reidModel';

type Models = {
  list: api.ModelChoice[] | null;
  error: string | null;
  chosen: api.ModelKey | null;
  load(): Promise<api.ModelChoice[]>;
  choose(key: api.ModelKey): void;
};

export const useModels = create<Models>((set, get) => ({
  list: null,
  error: null,
  chosen: Storage.getItemSync(KEY),
  async load() {
    try {
      const r = await api.models();
      const chosen = get().chosen;
      set({ list: r.models, error: null, chosen: r.models.some((m) => m.key === chosen) ? chosen : r.default });
      return r.models;
    } catch (e) {
      set({ list: null, error: (e as Error).message });
      return [];
    }
  },
  choose(key) {
    Storage.setItemSync(KEY, key);
    set({ chosen: key });
  },
}));

// The model that found the right tree most often on real phone photos (the server reports the measured rate).
export const recommended = (list: api.ModelChoice[]) =>
  list.reduce<api.ModelChoice | null>((best, m) => ((m.real_photo_top1 ?? -1) > (best?.real_photo_top1 ?? -1) ? m : best), null)?.key ?? null;

// measured on a 4-core laptop CPU: delta 0.2 s, gamma 2.4-2.7 s per photo (five 448 px crops)
export const speedLabel = (m: api.ModelChoice) => (m.speed === 'fast' ? 'Under 0.5 s a photo' : m.speed === 'slower' ? 'About 2 to 3 s a photo' : null);
