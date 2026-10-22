import Storage from './kv';
import { create } from 'zustand';
import type { IdentifyResult } from './api';
import type { ViewResult } from './engine/ondevice';
import type { Live } from './sensors';
import { nodeStatus, type NodeStatus } from './esp32';

export type Unit = { id: string; name: string; signal: 'Strong' | 'Weak' };
export type UnitStatus = Unit & { battery: number | null; storage: string; firmware: string };

// Transport-agnostic contract for the field unit. `link` is the ESP32 Wi-Fi node
// (firmware/esp32_wifi_node): the phone joins the unit's own Wi-Fi, then finds it at its address.
export interface DeviceLink {
  discover(): Promise<Unit[]>;
  connect(id: string): Promise<UnitStatus>;
  disconnect(): Promise<void>;
}

const asUnit = (st: NodeStatus): Unit => ({ id: st.device, name: st.device, signal: 'Strong' });
export const link: DeviceLink = {
  // One unit per Wi-Fi network: the one answering at the node address, if any.
  discover: () => nodeStatus().then((st) => [asUnit(st)], () => []),
  async connect(id) {
    const st = await nodeStatus();
    if (st.device !== id) throw new Error(`${id} is not in range. Join its Wi-Fi network first.`);
    return {
      ...asUnit(st),
      battery: st.battery_pct,
      storage: `${st.log_count} readings logged`,
      firmware: st.simulated ? `${st.firmware} · simulated sensors` : st.firmware,
    };
  },
  disconnect: async () => {},
};

export const PAIRED = 'pairedUnit'; // the last unit paired with this phone
const AUTO = 'unitAuto'; // 'off' after the user disconnects: the app stops connecting to the unit by itself
export const autoConnect = () => Storage.getItemSync(AUTO) !== 'off';

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
  // The sensor unit's reading taken with the photos (null: no unit connected; the scan is camera-only).
  sensors: Live | null;
  // Phone-only mode: the photos' fingerprints from the on-device model, stored with a new or matched tree.
  fingerprints: { model: string; embeddings: string[] } | null;
  // Phone-only mode: each photo as checked by the on-device model while scanning (null: not checked on the phone).
  views: ViewResult[] | null;
  setScan(s: Partial<Pick<App, 'photos' | 'treeId' | 'observationId' | 'isNew' | 'serverResult' | 'sensors' | 'fingerprints' | 'views'>>): void;
};

export const useApp = create<App>((set) => ({
  unit: null,
  connecting: null,
  async connect(id) {
    set({ connecting: id });
    try {
      set({ unit: await link.connect(id) });
      Storage.setItemSync(PAIRED, id);
      Storage.removeItemSync(AUTO);
    } finally {
      set({ connecting: null });
    }
  },
  async disconnect() {
    await link.disconnect();
    Storage.removeItemSync(PAIRED);
    Storage.setItemSync(AUTO, 'off');
    set({ unit: null });
  },
  photos: [],
  treeId: null,
  observationId: null,
  isNew: false,
  serverResult: null,
  sensors: null,
  fingerprints: null,
  views: null,
  setScan: (s) => set(s),
}));

// Reconnecting is done by the live link (sensors.ts): any unit answering on this Wi-Fi is connected.
