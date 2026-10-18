import * as Location from 'expo-location';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Switch, TextInput, View } from 'react-native';
import type { Sensors } from '@/api';
import { LEVELS, NO_CHECKS, overall, saveScan, saveServerVisit, type Checks, type Levels } from '@/data';
import { useDb } from '@/db';
import { useApp } from '@/device';
import { Check, Cpu } from '@/icons';
import { isServer } from '@/session';
import { color, font, radius, space, status } from '@/theme';
import { BackBar, Button, Card, Dot, Icon, Screen, Segmented, T, notify } from '@/ui';

const OPTIONS = LEVELS.map((label, value) => ({ label, value }));

// ESP32 readings: label, unit, valid range (same as the backend)
const READINGS: { key: keyof Sensors; label: string; unit: string; min: number; max: number }[] = [
  { key: 'soil_moisture_pct', label: 'Soil moisture', unit: '%', min: 0, max: 100 },
  { key: 'air_temp_c', label: 'Air temp', unit: '°C', min: -40, max: 60 },
  { key: 'humidity_pct', label: 'Humidity', unit: '%', min: 0, max: 100 },
  { key: 'light_lux', label: 'Light', unit: 'lux', min: 0, max: 200000 },
];

export default function Health() {
  const db = useDb();
  const { photos, treeId, observationId, isNew } = useApp();
  const [levels, setLevels] = useState<Levels>({ wool: 0, needles: 0, crown: 0, dieback: 0 });
  const [checks, setChecks] = useState<Checks>(NO_CHECKS);
  const [readings, setReadings] = useState<Record<string, string>>({});
  const [note, setNote] = useState('');
  const [place, setPlace] = useState('');
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const st = status[overall(levels, checks)];
  const server = isServer();
  const set = (patch: Partial<Checks>) => setChecks((c) => ({ ...c, ...patch }));

  // New trees get a location fix while the user fills in the form.
  useEffect(() => {
    if (treeId) return;
    (async () => {
      if (!(await Location.requestForegroundPermissionsAsync()).granted) return;
      const { coords: c } = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setCoords({ lat: c.latitude, lng: c.longitude });
    })().catch(() => {});
  }, [treeId]);

  const parsed = Object.fromEntries(READINGS.map((r) => {
    const raw = (readings[r.key] ?? '').trim().replace(',', '.');
    const v = raw === '' ? null : Number(raw);
    return [r.key, v];
  })) as Sensors;
  const bad = READINGS.filter((r) => { const v = parsed[r.key]; return v != null && !(Number.isFinite(v) && v >= r.min && v <= r.max); });

  const save = async () => {
    if (bad.length) return notify('Check the sensor values', bad.map((r) => `${r.label}: ${r.min} to ${r.max} ${r.unit}`).join('\n'));
    setSaving(true);
    try {
      // Signed in, the visit already exists on the server (stored with the photos); add the health check.
      const id = observationId && treeId
        ? (await saveServerVisit(observationId, levels, note, checks, parsed), treeId)
        : await saveScan(db, { treeId: treeId ?? undefined, place, coords, photos, levels, note });
      useApp.getState().setScan({ photos: [], treeId: null, observationId: null, isNew: false });
      router.dismissAll();
      router.push(`/tree/${id}`);
    } catch (e) {
      notify('Could not save scan', String(e));
      setSaving(false);
    }
  };

  const grade = (key: keyof Levels, label: string, hint?: string) => (
    <View style={{ gap: space.sm }}>
      <View style={{ gap: 2 }}>
        <T v="label">{label}</T>
        {hint ? <T v="caption" style={{ fontSize: 12 }}>{hint}</T> : null}
      </View>
      <Segmented options={OPTIONS} value={levels[key]} onChange={(v) => setLevels({ ...levels, [key]: v })} />
    </View>
  );
  const chip = (key: keyof Checks, label: string) => {
    const on = checks[key];
    return (
      <Pressable key={key} onPress={() => set({ [key]: !on })} accessibilityRole="checkbox" accessibilityState={{ checked: on }} style={[s.chip, on && s.chipOn]}>
        {on && <Icon as={Check} c={color.paper} />}
        <T v="caption" c={on ? color.paper : color.ink} style={{ fontFamily: font.medium, fontSize: 14 }}>{label}</T>
      </Pressable>
    );
  };

  return (
    <Screen scroll>
      <BackBar title={`${isNew ? `New tree ${treeId ?? ''}`.trim() : treeId} · step 2 of 2`} />
      <View style={{ gap: space.sm }}>
        <T v="display">How does it look?</T>
        <T c={color.inkSoft}>Only what you can see. Anything you skip is recorded as “not checked”, not as healthy.</T>
      </View>

      {!treeId && (
        <View style={{ gap: space.sm }}>
          <T v="label">Place name</T>
          <TextInput value={place} onChangeText={setPlace} placeholder="For example, Ridge Trail" placeholderTextColor={color.inkSoft} style={s.input} />
          <T v="caption">{coords ? 'Location saved' : 'Getting location'}</T>
        </View>
      )}

      <Card style={s.card}>
        <View style={s.between}>
          <View style={{ flex: 1, gap: 2 }}>
            <T v="title">1. Under the twigs</T>
            <T v="caption" style={{ fontSize: 12 }}>Turn over a few low branches. This is the only way to confirm the insects.</T>
          </View>
          <Switch value={checks.twigsChecked} onValueChange={(v) => set({ twigsChecked: v, ...(v ? {} : { scale: false }) })}
            trackColor={{ true: color.spruce, false: color.line }} thumbColor={color.card} accessibilityLabel="I checked under the twigs" />
        </View>
        {checks.twigsChecked ? (
          <>
            {grade('wool', 'White woolly masses at needle bases', 'Hemlock woolly adelgid')}
            <View style={s.chips}>
              {chip('scale', 'Brown or white scale covers under needles')}
            </View>
          </>
        ) : (
          <T v="caption">Not checked: woolly adelgid and hemlock scale will show as “not assessed”.</T>
        )}
      </Card>

      <Card style={s.card}>
        <T v="title">2. The crown</T>
        {grade('needles', 'Needle loss', 'You can see through the crown')}
        {grade('crown', 'Dull, gray-green crown')}
        {grade('dieback', 'Twig and branch dieback')}
        <View style={s.chips}>{chip('banding', 'Yellow bands on needle tops')}</View>
      </Card>

      <Card style={s.card}>
        <T v="title">3. Trunk and soil</T>
        <View style={s.chips}>
          {chip('browning', 'Browning in a dry spell')}
          {chip('borers', 'Small exit holes in bark')}
          {chip('rootRot', 'Fungus or mushrooms at the base')}
        </View>
      </Card>

      {server && (
        <Card style={s.card}>
          <View style={s.inline}>
            <Icon as={Cpu} c={color.spruce} />
            <T v="title" style={{ flex: 1 }}>4. ESP32 readings</T>
            <T v="caption">optional</T>
          </View>
          <View style={s.grid}>
            {READINGS.map((r) => {
              const wrong = bad.includes(r);
              return (
                <View key={r.key} style={s.cell}>
                  <T v="caption" c={wrong ? status.infested.text : color.inkSoft}>{`${r.label} (${r.unit})`}</T>
                  <TextInput value={readings[r.key] ?? ''} onChangeText={(t) => setReadings({ ...readings, [r.key]: t })}
                    placeholder="N/A" placeholderTextColor={color.lichen} keyboardType="decimal-pad" accessibilityLabel={r.label}
                    style={[s.input, s.num, wrong && { borderColor: status.infested.dot }]} />
                </View>
              );
            })}
          </View>
          <T v="caption" style={{ fontSize: 12 }}>Type what the sensor node shows; blank means N/A. Low soil moisture, heat and dry air raise drought-stress risk.</T>
        </Card>
      )}

      <View style={[s.overall, { backgroundColor: st.tint }]}>
        <View style={{ gap: 2 }}>
          <T v="caption">Overall status</T>
          <T v="title">{st.label}</T>
        </View>
        <Dot c={st.dot} size={12} />
      </View>

      <TextInput value={note} onChangeText={setNote} placeholder="Add a note (optional)" placeholderTextColor={color.inkSoft} style={[s.input, s.note]} multiline />
      <Button title={saving ? 'Saving' : 'Save and see diagnosis'} onPress={save} disabled={saving} />
    </Screen>
  );
}

const s = StyleSheet.create({
  card: { padding: space.lg, gap: space.lg },
  between: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  inline: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: color.paper, borderWidth: 1, borderColor: color.lineStrong },
  chipOn: { backgroundColor: color.spruce, borderColor: color.spruce },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: space.md },
  cell: { flexBasis: '45%', flexGrow: 1, gap: 4 },
  input: { minHeight: 48, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink },
  num: { backgroundColor: color.paper },
  note: { minHeight: 96, paddingTop: space.md, textAlignVertical: 'top' },
  overall: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: space.lg, borderRadius: radius.md },
});
