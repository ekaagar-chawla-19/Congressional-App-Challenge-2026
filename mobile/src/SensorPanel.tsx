import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import type { Sensors } from './api';
import { useApp } from './device';
import { Cpu, Droplet, Droplets, RefreshCw, Sun, Thermometer, type LucideIcon } from './icons';
import { interpret, LOW_BATTERY, measureNow, present, useConnected, useSensors, type Live, type Note } from './sensors';
import { color, radius, space, status } from './theme';
import { Button, Card, Dot, Icon, T } from './ui';

// Sensor UI shared by every screen. Each piece renders nothing when there is nothing to show, and only the
// sensors a reading actually has: a unit with just a soil probe shows just soil moisture.

const ICON: Record<keyof Sensors, LucideIcon> = { soil_moisture_pct: Droplets, air_temp_c: Thermometer, humidity_pct: Droplet, light_lux: Sun };

export function fmt(key: keyof Sensors, v: number) {
  if (key === 'light_lux') return `~${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : Math.round(v)} lx`; // rough estimate
  if (key === 'air_temp_c') return `${Math.round(v * 10) / 10} °C`;
  return `${Math.round(v)}%`;
}

/** One line for lists: "Soil 34% · 21.5 °C · RH 60% · ~420 lx". */
export const sensorLine = (s: Sensors | null | undefined) => present(s).map((r) => (r.key === 'humidity_pct' ? `RH ${fmt(r.key, s![r.key]!)}` : r.key === 'soil_moisture_pct' ? `Soil ${fmt(r.key, s![r.key]!)}` : fmt(r.key, s![r.key]!))).join(' · ');

/** Tiles for the sensors this reading has. dark: on the camera screen. */
export function SensorTiles({ sensors, dark }: { sensors: Sensors | null | undefined; dark?: boolean }) {
  const shown = present(sensors);
  if (!shown.length) return null;
  return (
    <View style={[s.tiles, dark && s.tilesDark]}>
      {shown.map((r) => (
        <View key={r.key} style={[s.tile, dark && s.tileDark]} accessibilityLabel={`${r.label} ${fmt(r.key, sensors![r.key]!)}`}>
          {dark ? <SmallIcon k={r.key} /> : <Icon as={ICON[r.key]} c={color.inkSoft} />}
          {dark ? (
            // over the viewfinder: one compact row of icon + value, clear of the framing corners
            <T v="label" c={color.paper} style={{ fontSize: 13 }}>{fmt(r.key, sensors![r.key]!)}</T>
          ) : (
            <View style={{ gap: 2 }}>
              <T v="caption" style={{ fontSize: 12 }}>{r.label}</T>
              <T v="label">{fmt(r.key, sensors![r.key]!)}</T>
            </View>
          )}
        </View>
      ))}
    </View>
  );
}

const SmallIcon = ({ k }: { k: keyof Sensors }) => {
  const G = ICON[k];
  return <G size={16} strokeWidth={1.75} color={color.paper} />;
};

const TONE: Record<Note['tone'], string> = { good: status.healthy.dot, warn: status.watch.dot, bad: status.infested.dot };
export function Notes({ sensors }: { sensors: Sensors | null | undefined }) {
  const notes = interpret(sensors);
  if (!notes.length) return null;
  return (
    <View style={{ gap: space.xs }}>
      {notes.map((n) => (
        <View key={n.text} style={s.note}>
          <Dot c={TONE[n.tone]} />
          <T v="caption" c={color.ink} style={{ flex: 1 }}>{n.text}</T>
        </View>
      ))}
    </View>
  );
}

const ago = (t: number) => {
  const sec = Math.round((Date.now() - t) / 1000);
  return sec < 10 ? 'just now' : sec < 60 ? `${sec} s ago` : `${Math.round(sec / 60)} min ago`;
};

/** Live readings from the connected unit (home, device page). Nothing when no unit is connected. */
export function LiveSensorCard() {
  const connected = useConnected();
  const live = useSensors((s) => s.live);
  const measuring = useSensors((s) => s.measuring);
  const battery = useApp((s) => s.unit?.battery ?? null);
  if (!connected || !live) return null;
  return (
    <Card style={s.card}>
      <View style={s.head}>
        <Icon as={Cpu} c={color.spruce} />
        <View style={{ flex: 1 }}>
          <T v="title">Live sensors</T>
          <T v="caption">{`${live.device} · ${ago(live.at)}${battery == null ? '' : ` · battery ${battery}%`}`}</T>
        </View>
        <T v="label" c={color.spruce} onPress={measuring ? undefined : () => measureNow().catch(() => {})} style={{ padding: space.sm }}>
          {measuring ? 'Reading…' : 'Measure'}
        </T>
      </View>
      <SensorTiles sensors={live.sensors} />
      <Notes sensors={live.sensors} />
      {battery != null && battery < LOW_BATTERY && (
        <View style={s.note}>
          <Dot c={TONE.warn} />
          <T v="caption" c={color.ink} style={{ flex: 1 }}>{`Unit battery low (${battery}%): charge it soon. When it runs out, the unit switches itself off to protect the battery.`}</T>
        </View>
      )}
    </Card>
  );
}

/**
 * The reading attached to one visit (health check, "add reading"). value: the reading taken with the
 * photos, or null. Shown when there is a reading or a unit to take one; otherwise nothing at all.
 */
export function VisitSensors({ title, value, onChange }: { title: string; value: Live | null; onChange(v: Live | null): void }) {
  const connected = useConnected();
  const [error, setError] = useState<string | null>(null);
  const measuring = useSensors((st) => st.measuring);
  if (!value && !connected) return null;
  const read = async () => {
    setError(null);
    try {
      onChange(await measureNow());
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Card style={s.card}>
      <View style={s.head}>
        <Icon as={Cpu} c={color.spruce} />
        <View style={{ flex: 1 }}>
          <T v="title">{title}</T>
          <T v="caption">{value ? `${value.device} · taken ${ago(value.at)}` : 'Sensor unit connected'}</T>
        </View>
      </View>
      {value ? (
        <>
          <SensorTiles sensors={value.sensors} />
          <Notes sensors={value.sensors} />
        </>
      ) : (
        <T v="caption">Take a reading at this tree to add soil, air and light to the diagnosis.</T>
      )}
      {error && <T v="caption" c={status.infested.text}>{error}</T>}
      <View style={s.split}>
        {connected && (
          <View style={{ flex: 1 }}>
            <Button title={measuring ? 'Reading…' : value ? 'Read again' : 'Read sensors'} icon={RefreshCw} secondary={!!value} onPress={read} disabled={measuring} />
          </View>
        )}
        {value && (
          <View style={{ flex: 1 }}>
            <Button title="Don't save it" secondary onPress={() => onChange(null)} />
          </View>
        )}
      </View>
    </Card>
  );
}

/** For screens that need a unit (e.g. "add reading") when none is connected. */
export function PairPrompt() {
  return (
    <Card style={s.card}>
      <View style={s.head}>
        <Icon as={Cpu} c={color.inkSoft} />
        <T v="title" style={{ flex: 1 }}>No sensor unit connected</T>
      </View>
      <T v="caption">Turn the unit on and join its Wi-Fi (HS-ESP32-xxxx). It connects by itself.</T>
      <Button title="Pair a unit" secondary onPress={() => router.push('/pair')} />
    </Card>
  );
}

const s = StyleSheet.create({
  card: { padding: space.lg, gap: space.md },
  head: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  tile: { flexBasis: '47%', flexGrow: 1, flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: radius.sm, backgroundColor: color.paper },
  tilesDark: { flexWrap: 'nowrap', gap: 6, justifyContent: 'center' },
  tileDark: { flexBasis: 'auto', flexGrow: 0, paddingVertical: 6, paddingHorizontal: 8, gap: 4, borderRadius: 999, backgroundColor: 'rgba(22, 32, 28, 0.72)' },
  note: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  split: { flexDirection: 'row', gap: space.md },
});
