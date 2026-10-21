import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import * as api from '@/api';
import { Esp32Readings, hasReading, parseFields, type ReadingFields } from '@/Esp32Readings';
import { quickFix } from '@/identify';
import { color, font, radius, space, status } from '@/theme';
import { BackBar, Button, Card, Row, Screen, T, notify } from '@/ui';

const LEVEL = { likely: status.infested, possible: status.watch, low: status.healthy, unknown: status.unrated } as const;
const LABEL = { likely: 'Likely', possible: 'Possible', low: 'Unlikely', unknown: 'Not checked' } as const;

// Add more data to a known tree without photos: an ESP32 reading (and a note). The server stores it as a
// visit and re-runs the diagnosis, which is shown right away.
export default function AddReading() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [fields, setFields] = useState<ReadingFields>({});
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<api.Finding[] | null>(null);
  const { sensors, bad } = parseFields(fields);

  const save = async () => {
    if (bad.length) return notify('Check the sensor values', bad.map((r) => `${r.label}: ${r.min} to ${r.max} ${r.unit}`).join('\n'));
    if (!hasReading(sensors) && !note.trim()) return notify('Nothing to save', 'Read the ESP32, paste its reading, or type at least one value.');
    setSaving(true);
    try {
      await api.addVisit(id, { sensors: hasReading(sensors) ? sensors : null, health_notes: note.trim() || null, location: await quickFix() });
      // The tree's diagnosis now: the latest assessed finding per condition, this reading included.
      setSaved((await api.tree(id)).current_conditions);
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
        <Card>
          {shown.map((f, i) => (
            <Row key={f.condition} title={f.name} sub={f.evidence.slice(0, 2).join(' · ')} last={i === shown.length - 1}
              right={<View style={[s.level, { backgroundColor: LEVEL[f.level].tint }]}><T v="caption" c={LEVEL[f.level].text} style={{ fontFamily: font.semibold }}>{LABEL[f.level]}</T></View>} />
          ))}
        </Card>
        <Button title="Back to the tree" onPress={() => router.back()} />
        <Button title="Add another reading" secondary onPress={() => (setSaved(null), setFields({}), setNote(''))} />
      </Screen>
    );
  }

  return (
    <Screen scroll>
      <BackBar title={`${id} · add reading`} />
      <View style={{ gap: space.sm }}>
        <T v="display">Add an ESP32 reading</T>
        <T c={color.inkSoft}>{"Stand at the tree with the sensor node. No photos needed: the reading is added to this tree's history."}</T>
      </View>
      <Esp32Readings title="ESP32 readings" optional={false} fields={fields} onChange={setFields} />
      <TextInput value={note} onChangeText={setNote} placeholder="Add a note (optional)" placeholderTextColor={color.inkSoft} style={s.note} multiline />
      <Button title={saving ? 'Saving' : 'Save and update diagnosis'} onPress={save} disabled={saving} />
    </Screen>
  );
}

const s = StyleSheet.create({
  note: { minHeight: 88, paddingHorizontal: space.lg, paddingTop: space.md, borderRadius: 14, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink, textAlignVertical: 'top' },
  level: { paddingHorizontal: 10, height: 26, borderRadius: radius.pill, justifyContent: 'center' },
});
