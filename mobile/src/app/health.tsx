import * as Location from 'expo-location';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Switch, TextInput, View } from 'react-native';
import { LEVELS, NO_CHECKS, overall, saveScan, saveServerVisit, type Checks, type Levels } from '@/data';
import { useDb } from '@/db';
import { useApp } from '@/device';
import { Check } from '@/icons';
import { VisitSensors } from '@/SensorPanel';
import type { Live } from '@/sensors';
import { color, font, radius, space, status } from '@/theme';
import { BackBar, Button, Card, Dot, Icon, Screen, Segmented, T, notify } from '@/ui';

const OPTIONS = LEVELS.map((label, value) => ({ label, value }));

export default function Health() {
  const db = useDb();
  const { photos, treeId, observationId, isNew, sensors, fingerprints } = useApp();
  const [levels, setLevels] = useState<Levels>({ wool: 0, needles: 0, crown: 0, dieback: 0 });
  const [checks, setChecks] = useState<Checks>(NO_CHECKS);
  const [reading, setReading] = useState<Live | null>(sensors); // taken with the photos, if a unit was connected
  const [note, setNote] = useState('');
  const [place, setPlace] = useState('');
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState<'pending' | 'off' | 'done'>('pending');
  const [saving, setSaving] = useState(false);
  const st = status[overall(levels, checks)];
  const set = (patch: Partial<Checks>) => setChecks((c) => ({ ...c, ...patch }));

  // New trees get a location fix while the user fills in the form.
  useEffect(() => {
    if (treeId) return;
    (async () => {
      if (!(await Location.requestForegroundPermissionsAsync()).granted) return setLocating('off');
      const { coords: c } = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setCoords({ lat: c.latitude, lng: c.longitude });
      setLocating('done');
    })().catch(() => setLocating('off'));
  }, [treeId]);

  const save = async () => {
    setSaving(true);
    try {
      // Signed in, the visit already exists on the server (stored with the photos); add the health check.
      const id = observationId && treeId
        ? (await saveServerVisit(observationId, levels, note, checks, reading?.sensors ?? null, sensors != null), treeId)
        : await saveScan(db, { treeId: treeId ?? undefined, place, coords, photos, levels, note, checks, sensors: reading, fingerprints });
      useApp.getState().setScan({ photos: [], treeId: null, observationId: null, isNew: false, sensors: null, fingerprints: null });
      router.dismissAll();
      router.push(`/tree/${id}`);
    } catch (e) {
      notify('Could not save scan', (e as Error).message ?? String(e));
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
          <T v="caption">{coords ? 'Location saved' : locating === 'off' ? "No location (location is off for HemlockID): the tree won't appear on the map." : 'Getting location…'}</T>
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

      <VisitSensors title="4. Sensor reading" value={reading} onChange={setReading} />

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
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: color.paper, borderWidth: 1, borderColor: color.lineStrong },
  chipOn: { backgroundColor: color.spruce, borderColor: color.spruce },
  input: { minHeight: 48, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink },
  note: { minHeight: 96, paddingTop: space.md, textAlignVertical: 'top' },
  overall: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: space.lg, borderRadius: radius.md },
});
