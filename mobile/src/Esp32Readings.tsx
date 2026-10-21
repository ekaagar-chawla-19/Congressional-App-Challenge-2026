import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import type { Sensors } from './api';
import { canReadOverBluetooth, parseEsp32Reading, readOverBluetooth, READINGS } from './esp32';
import { Cpu, Wifi } from './icons';
import { color, font, space, status } from './theme';
import { Button, Card, Icon, T } from './ui';

export type ReadingFields = Record<string, string>; // what is typed in each box ('' = N/A)

/** The typed boxes as sensors for the API, plus the readings outside their valid range. */
export function parseFields(fields: ReadingFields): { sensors: Sensors; bad: typeof READINGS } {
  const sensors = Object.fromEntries(READINGS.map((r) => {
    const raw = (fields[r.key] ?? '').trim().replace(',', '.');
    return [r.key, raw === '' ? null : Number(raw)];
  })) as Sensors;
  const bad = READINGS.filter((r) => { const v = sensors[r.key]; return v != null && !(Number.isFinite(v) && v >= r.min && v <= r.max); });
  return { sensors, bad };
}
export const hasReading = (s: Sensors) => READINGS.some((r) => s[r.key] != null);

// The ESP32 sensor node's four readings: read over Bluetooth where the browser can, paste the node's JSON
// line, or type the numbers. Low soil moisture, heat and dry air feed the drought-stress diagnosis.
export function Esp32Readings({ title = 'ESP32 readings', optional = true, fields, onChange }: {
  title?: string; optional?: boolean; fields: ReadingFields; onChange(f: ReadingFields): void;
}) {
  const [paste, setPaste] = useState<string | null>(null);
  const [device, setDevice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const { bad } = parseFields(fields);
  const fill = (s: Sensors, dev: string | null) => {
    onChange(Object.fromEntries(READINGS.map((r) => [r.key, s[r.key] == null ? '' : String(s[r.key])])));
    setDevice(dev);
    setError(null);
  };
  const fromBluetooth = async () => {
    setReading(true);
    try {
      const r = await readOverBluetooth();
      fill(r.sensors, r.device);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReading(false);
    }
  };
  const usePaste = () => {
    try {
      const r = parseEsp32Reading(paste ?? '');
      fill(r.sensors, r.device);
      setPaste(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Card style={s.card}>
      <View style={s.inline}>
        <Icon as={Cpu} c={color.spruce} />
        <T v="title" style={{ flex: 1 }}>{title}</T>
        {optional && <T v="caption">optional</T>}
      </View>
      {device && <T v="caption" c={color.spruce} style={{ fontFamily: font.medium }}>{`Reading from ${device}`}</T>}
      <View style={s.grid}>
        {READINGS.map((r) => {
          const wrong = bad.includes(r);
          return (
            <View key={r.key} style={s.cell}>
              <T v="caption" c={wrong ? status.infested.text : color.inkSoft}>{`${r.label} (${r.unit})`}</T>
              <TextInput value={fields[r.key] ?? ''} onChangeText={(t) => onChange({ ...fields, [r.key]: t })}
                placeholder="N/A" placeholderTextColor={color.lichen} keyboardType="decimal-pad" accessibilityLabel={r.label}
                style={[s.input, wrong && { borderColor: status.infested.dot }]} />
            </View>
          );
        })}
      </View>
      {paste !== null && (
        <View style={{ gap: space.sm }}>
          <TextInput value={paste} onChangeText={setPaste} multiline autoCapitalize="none" autoCorrect={false}
            placeholder='{"v":1,"device":"HS-ESP32-…","soil_moisture_pct":31.5,…}' placeholderTextColor={color.lichen}
            accessibilityLabel="ESP32 reading JSON" style={[s.input, s.paste]} />
          <View style={s.split}>
            <View style={{ flex: 1 }}><Button title="Use reading" onPress={usePaste} disabled={!paste?.trim()} /></View>
            <View style={{ flex: 1 }}><Button title="Cancel" secondary onPress={() => (setPaste(null), setError(null))} /></View>
          </View>
        </View>
      )}
      {error && <T v="caption" c={status.infested.text}>{error}</T>}
      {paste === null && (
        <View style={s.split}>
          {canReadOverBluetooth() && (
            <View style={{ flex: 1 }}><Button title={reading ? 'Reading…' : 'Read from ESP32'} icon={Wifi} onPress={fromBluetooth} disabled={reading} /></View>
          )}
          <View style={{ flex: 1 }}><Button title="Paste reading" secondary onPress={() => setPaste('')} /></View>
        </View>
      )}
      <T v="caption" style={{ fontSize: 12 }}>
        {canReadOverBluetooth()
          ? 'Read the node over Bluetooth, paste the line it prints, or type the numbers. Blank means N/A.'
          : 'Paste the line the node prints (serial monitor or a BLE app such as nRF Connect), or type the numbers. Blank means N/A.'}
      </T>
    </Card>
  );
}

const s = StyleSheet.create({
  card: { padding: space.lg, gap: space.lg },
  inline: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: space.md },
  cell: { flexBasis: '45%', flexGrow: 1, gap: 4 },
  split: { flexDirection: 'row', gap: space.md },
  input: { minHeight: 48, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.paper, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink },
  paste: { minHeight: 88, paddingTop: space.md, textAlignVertical: 'top', fontSize: 13 },
});
