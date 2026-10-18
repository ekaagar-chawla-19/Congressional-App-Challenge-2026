import * as Location from 'expo-location';
import { router } from 'expo-router';
import { useDb } from '@/db';
import { useEffect, useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import { LEVELS, overall, saveScan, saveServerVisit, SIGNS, type Levels } from '@/data';
import { useApp } from '@/device';
import { color, font, radius, space, status } from '@/theme';
import { BackBar, Button, Dot, Screen, Segmented, T, notify } from '@/ui';

const OPTIONS = LEVELS.map((label, value) => ({ label, value }));

export default function Health() {
  const db = useDb();
  const { photos, treeId, observationId, isNew } = useApp();
  const [levels, setLevels] = useState<Levels>({ wool: 0, needles: 0, crown: 0, dieback: 0 });
  const [note, setNote] = useState('');
  const [place, setPlace] = useState('');
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const st = status[overall(levels)];

  // New trees get a location fix while the user fills in the form.
  useEffect(() => {
    if (treeId) return;
    (async () => {
      if (!(await Location.requestForegroundPermissionsAsync()).granted) return;
      const { coords: c } = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setCoords({ lat: c.latitude, lng: c.longitude });
    })().catch(() => {});
  }, [treeId]);

  const save = async () => {
    setSaving(true);
    try {
      // Signed in, the visit already exists on the server (stored with the photos); add the health check.
      const id = observationId && treeId
        ? (await saveServerVisit(observationId, levels, note), treeId)
        : await saveScan(db, { treeId: treeId ?? undefined, place, coords, photos, levels, note });
      useApp.getState().setScan({ photos: [], treeId: null, observationId: null, isNew: false });
      router.dismissAll();
      router.push(`/tree/${id}`);
    } catch (e) {
      notify('Could not save scan', String(e));
      setSaving(false);
    }
  };

  return (
    <Screen scroll>
      <BackBar title={`${isNew ? `New tree ${treeId ?? ''}`.trim() : treeId} · step 2 of 2`} />
      <View style={{ gap: space.sm }}>
        <T v="display">How does it look?</T>
        <T c={color.inkSoft}>Check the undersides of a few low branches.</T>
      </View>

      {!treeId && (
        <View style={{ gap: space.sm }}>
          <T v="label">Place name</T>
          <TextInput value={place} onChangeText={setPlace} placeholder="For example, Ridge Trail" placeholderTextColor={color.inkSoft} style={s.input} />
          <T v="caption">{coords ? 'Location saved' : 'Getting location'}</T>
        </View>
      )}

      {SIGNS.map(({ key, label }) => (
        <View key={key} style={{ gap: space.sm }}>
          <T v="label">{label}</T>
          <Segmented options={OPTIONS} value={levels[key]} onChange={(v) => setLevels({ ...levels, [key]: v })} />
        </View>
      ))}

      <View style={[s.overall, { backgroundColor: st.tint }]}>
        <View style={{ gap: 2 }}>
          <T v="caption">Overall status</T>
          <T v="title">{st.label}</T>
        </View>
        <Dot c={st.dot} size={12} />
      </View>

      <TextInput value={note} onChangeText={setNote} placeholder="Add a note (optional)" placeholderTextColor={color.inkSoft} style={[s.input, s.note]} multiline />
      <Button title={saving ? 'Saving' : 'Save scan'} onPress={save} disabled={saving} />
    </Screen>
  );
}

const s = StyleSheet.create({
  input: { minHeight: 48, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink },
  note: { minHeight: 96, paddingTop: space.md, textAlignVertical: 'top' },
  overall: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: space.lg, borderRadius: radius.md },
});
