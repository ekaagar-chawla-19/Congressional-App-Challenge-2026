import { Platform } from 'react-native';
import { parseEsp32Reading, type Esp32Reading } from './esp32reading';

export { parseEsp32Reading, READINGS, type Esp32Reading } from './esp32reading';

// The ESP32 sensor node (firmware/esp32_sensors): Bluetooth LE identifiers, the reading format, and a reader.
// Same rules as the backend (src/hemlock_sentinel/esp32/reading.py) and client/src/esp32.ts.
export const ESP32 = {
  service: '6e1f0001-6d6c-4f2b-9a35-1c3a5e6b7d01',
  reading: '6e1f0002-6d6c-4f2b-9a35-1c3a5e6b7d01', // read / notify: reading JSON
  command: '6e1f0003-6d6c-4f2b-9a35-1c3a5e6b7d01', // write "r": measure now
  namePrefix: 'HS-ESP32',
  measureWaitMs: 3000,
} as const;

type Bluetooth = { requestDevice(o: unknown): Promise<{ name?: string; gatt?: { connect(): Promise<Gatt> } }> };
type Gatt = { disconnect(): void; getPrimaryService(u: string): Promise<{ getCharacteristic(u: string): Promise<Char> }> };
type Char = {
  writeValue?(v: BufferSource): Promise<void>; writeValueWithoutResponse?(v: BufferSource): Promise<void>;
  readValue(): Promise<DataView>; startNotifications?(): Promise<Char>; addEventListener?(t: string, f: (e: { target: { value: DataView } }) => void): void;
};
const bluetooth = (): Bluetooth | null =>
  Platform.OS === 'web' ? ((globalThis.navigator as unknown as { bluetooth?: Bluetooth })?.bluetooth ?? null) : null;

/** Reading straight from the node needs Web Bluetooth (Chrome on Android, Windows, macOS; not iPhone Safari or Expo Go). */
export const canReadOverBluetooth = () => bluetooth() !== null;

/** Pick the node, ask it to measure, wait for the reading (notification, or read after the measuring time). */
export async function readOverBluetooth(): Promise<Esp32Reading> {
  const bt = bluetooth();
  if (!bt) throw new Error('This browser cannot use Bluetooth. Paste the reading instead.');
  const dev = await bt.requestDevice({ filters: [{ namePrefix: ESP32.namePrefix }], optionalServices: [ESP32.service] });
  const gatt = await dev.gatt!.connect();
  try {
    const svc = await gatt.getPrimaryService(ESP32.service);
    const reading = await svc.getCharacteristic(ESP32.reading);
    const command = await svc.getCharacteristic(ESP32.command);
    const text = (v: DataView) => new TextDecoder().decode(v);
    const notified = new Promise<string>((resolve) => {
      reading.startNotifications?.().then(() => reading.addEventListener?.('characteristicvaluechanged', (e) => resolve(text(e.target.value)))).catch(() => {});
    });
    const r = new TextEncoder().encode('r');
    await (command.writeValueWithoutResponse ? command.writeValueWithoutResponse(r) : command.writeValue!(r));
    const timeout = new Promise<null>((res) => setTimeout(() => res(null), ESP32.measureWaitMs + 1500));
    const got = (await Promise.race([notified, timeout])) ?? text(await reading.readValue());
    const p = parseEsp32Reading(got);
    return { ...p, device: p.device ?? dev.name ?? null };
  } finally {
    gatt.disconnect();
  }
}
