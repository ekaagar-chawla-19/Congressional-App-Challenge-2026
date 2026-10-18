import Storage from './kv';
import { create } from 'zustand';
import type { IdentifyResult } from './api';

export type Unit = { id: string; name: string; signal: 'Strong' | 'Weak' };
export type UnitStatus = Unit & { battery: number; storage: string; firmware: string };

// Transport-agnostic contract for the field unit. The hardware and its link (BLE or Wi-Fi)
// are not decided yet, so the app talks to this interface and `link` is a mock for now.
export interface DeviceLink {
  discover(): Promise<Unit[]>;
  connect(id: string): Promise<UnitStatus>;
  disconnect(): Promise<void>;
}

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const MOCK_UNITS: Unit[] = [
  { id: 'A4F2', name: 'Unit A4F2', signal: 'Strong' },
  { id: '7C10', name: 'Unit 7C10', signal: 'Weak' },
];
export const link: DeviceLink = {
  discover: () => wait(1200).then(() => MOCK_UNITS),
  async connect(id) {
    await wait(800);
    const unit = MOCK_UNITS.find((u) => u.id === id);
    if (!unit) throw new Error(`Unit ${id} is not in range`);
    return { ...unit, battery: 82, storage: '3.1 of 16 GB', firmware: 'Up to date' };
  },
  disconnect: () => wait(200),
};

const PAIRED = 'pairedUnit';

type App = {
  unit: UnitStatus | null;
  connecting: string | null;
  connect(id: string): Promise<void>;
  disconnect(): Promise<void>;
  // The scan in progress: photos taken, then the tree they were matched to (null = new tree).
  // Signed in, the server has already stored the visit (observationId) and created any new tree (isNew).
  photos: string[];
  treeId: string | null;
  observationId: string | null;
  isNew: boolean;
  // Set when the guided capture already asked the server which tree this is.
  serverResult: IdentifyResult | null;
  setScan(s: Partial<Pick<App, 'photos' | 'treeId' | 'observationId' | 'isNew' | 'serverResult'>>): void;
};

export const useApp = create<App>((set) => ({
  unit: null,
  connecting: null,
  async connect(id) {
    set({ connecting: id });
    try {
      set({ unit: await link.connect(id) });
      Storage.setItemSync(PAIRED, id);
    } finally {
      set({ connecting: null });
    }
  },
  async disconnect() {
    await link.disconnect();
    Storage.removeItemSync(PAIRED);
    set({ unit: null });
  },
  photos: [],
  treeId: null,
  observationId: null,
  isNew: false,
  serverResult: null,
  setScan: (s) => set(s),
}));

// Reconnect to the last paired unit on launch.
const paired = Storage.getItemSync(PAIRED);
if (paired) useApp.getState().connect(paired).catch(() => {});
