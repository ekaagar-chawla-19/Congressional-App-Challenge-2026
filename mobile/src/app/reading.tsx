import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import * as api from '@/api';
import { addLocalReading, getTree } from '@/data';
import { useDb } from '@/db';
import { quickFix } from '@/identify';
import { PairPrompt, VisitSensors } from '@/SensorPanel';
import { measureNow, useConnected, type Live } from '@/sensors';
import { isServer } from '@/session';
import { color, font, radius, space, status } from '@/theme';
import { BackBar, Button, Card, Row, Screen, T, notify } from '@/ui';

const LEVEL = { likely: status.infested, possible: status.watch, low: status.healthy, unknown: status.unrated } as const;
const LABEL = { likely: 'Likely', possible: 'Possible', low: 'Unlikely', unknown: 'Not checked' } as const;

// Add a sensor reading to a known tree without photos. It is stored as a visit and the diagnosis is re-run
// (by the server, or on the phone in phone-only mode), and the result is shown right away.
export default function AddReading() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const db = useDb();
  const connected = useConnected();
  const server = isServer();
  const [reading, setReading] = useState<Live | null>(null);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<api.Finding[] | null>(null);

  // Take a fresh reading once, as soon as the unit is there ("Don't save it" must not trigger another one).
  const measured = useRef(false);
  useEffect(() => {
    if (!connected || measured.current) return;
    measured.current = true;
    measureNow().then(setReading, () => {});
  }, [connected]);

  const save = async () => {
    if (!reading) return notify('No reading yet', 'Read the sensors first.');
    setSaving(true);
    try {
      if (server) await api.addVisit(id, { sensors: reading.sensors, health_notes: note.trim() || null, location: await quickFix() });
      else await addLocalReading(db, id, reading);
      // The tree's diagnosis now: the latest assessed finding per condition, this reading included.
      setSaved((await getTree(db, id)).extras?.conditions ?? []);
    } catch (e) {
      notify('Could not save the reading', (e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (saved) {
    const shown = [...saved].sort((a, b) => (a.level === 'unknown' ? 1 : 0) - (b.level === 'unknown' ? 1 : 0));
    return (
      <Screen scroll>
        <BackBar title={`${id} · reading saved`} />
        <T v="display">Updated diagnosis</T>
        <T c={color.inkSoft}>The reading was added to this tree as a new visit. Each condition shows its latest assessment, so signs seen on earlier visits still count.</T>
        {shown.length > 0 && (
          <Card>
            {shown.map((f, i) => (
              <Row key={f.condition} title={f.name} sub={f.evidence.slice(0, 2).join(' · ')} last={i === shown.length - 1}
                right={<View style={[s.level, { backgroundColor: LEVEL[f.level].tint }]}><T v="caption" c={LEVEL[f.level].text} style={{ fontFamily: font.semibold }}>{LABEL[f.level]}</T></View>} />
            ))}
          </Card>
        )}
        <Button title="Back to the tree" onPress={() => router.back()} />
        <Button title="Add another reading" secondary onPress={() => (setSaved(null), setReading(null), setNote(''), measureNow().then(setReading, () => {}))} />
      </Screen>
    );
  }

  return (
    <Screen scroll>
      <BackBar title={`${id} · add reading`} />
      <View style={{ gap: space.sm }}>
        <T v="display">Add a sensor reading</T>
        <T c={color.inkSoft}>{"Stand at the tree with the sensor unit. No photos needed: the reading is added to this tree's history."}</T>
      </View>
      {connected || reading ? <VisitSensors title="Sensor reading" value={reading} onChange={setReading} /> : <PairPrompt />}
      {server && (
        <TextInput value={note} onChangeText={setNote} placeholder="Add a note (optional)" placeholderTextColor={color.inkSoft} style={s.note} multiline />
      )}
      <Button title={saving ? 'Saving' : 'Save and update diagnosis'} onPress={save} disabled={saving || !reading} />
    </Screen>
  );
}

const s = StyleSheet.create({
  note: { minHeight: 88, paddingHorizontal: space.lg, paddingTop: space.md, borderRadius: radius.sm, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink, textAlignVertical: 'top' },
  level: { paddingHorizontal: 10, height: 26, borderRadius: radius.pill, justifyContent: 'center' },
});
