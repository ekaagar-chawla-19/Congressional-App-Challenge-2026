import { router, useLocalSearchParams } from 'expo-router';
import { useDb } from '@/db';
import { useState } from 'react';
import { Droplets, MapPin, ScanLine, Sun, Thermometer, type LucideIcon } from '@/icons';
import { Pressable, StyleSheet, View } from 'react-native';
import type { ConditionKey, Finding } from '@/api';
import { CONDITIONS, CONDITION_KEYS } from '@/conditions';
import { deleteTree, fmtDate, getTree, useQuery, type TreeExtras } from '@/data';
import { color, font, radius, space, status, type Status } from '@/theme';
import { BackBar, Badge, Button, Card, ConfirmDelete, DeleteLink, Icon, Photo, Row, Screen, T } from '@/ui';

const BAR: Record<Status, number> = { healthy: 20, watch: 40, infested: 64, unrated: 8 };
const LEVEL = {
  likely: { ...status.infested, label: 'Likely' },
  possible: { ...status.watch, label: 'Possible' },
  low: { ...status.healthy, label: 'Unlikely' },
  unknown: { ...status.unrated, label: 'Not checked' },
} as const;

export default function TreeDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const db = useDb();
  const data = useQuery((db) => getTree(db, id), id);
  const [confirm, setConfirm] = useState(false);
  if (!data?.tree) return <Screen>{data ? <BackBar title="Tree not found" /> : null}</Screen>;

  const { tree, scans } = data;
  const latest = scans[0];
  const shots = scans.map((sc) => ({ at: sc.created_at, uri: (JSON.parse(sc.photos) as string[])[0] })).filter((p) => p.uri).slice(0, 3);
  const history = scans.slice(0, 6).reverse();
  const trend = history.length < 2 ? 'Needs more visits' : BAR[latest.status] > BAR[history[0].status] ? 'Getting worse' : BAR[latest.status] < BAR[history[0].status] ? 'Improving' : 'Stable';
  const facts: [string, string][] = [
    ['Scans', `${scans.length} ${scans.length === 1 ? 'visit' : 'visits'}`],
    ['Last scan', latest ? fmtDate(latest.created_at) : 'None'],
    ['Location', tree.lat != null ? `${tree.lat.toFixed(4)}, ${tree.lng!.toFixed(4)}` : 'Not recorded'],
    ['Registered', fmtDate(tree.created_at)],
  ];

  return (
    <Screen scroll>
      <BackBar
        right={tree.lat != null && (
          <Pressable style={s.round} onPress={() => router.navigate(`/map?sel=${tree.id}`)} accessibilityLabel="Show on map">
            <Icon as={MapPin} />
          </Pressable>
        )}
      />

      <View style={s.head}>
        <View style={{ gap: 6, flex: 1 }}>
          <T v="hero">{tree.id}</T>
          <T c={color.inkSoft}>{tree.place}</T>
        </View>
        {latest && <Badge s={latest.status} />}
      </View>

      {data.extras && <ServerHealth {...data.extras} only="causes" />}

      {shots.length > 0 && (
        <View style={s.row}>
          {shots.map((p) => (
            <View key={p.at} style={s.fig}>
              <Photo uri={p.uri} height={88} />
              <T v="caption" style={{ fontSize: 12 }}>{new Date(p.at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</T>
            </View>
          ))}
        </View>
      )}

      <Card style={{ padding: space.lg, gap: space.lg }}>
        <View style={s.between}>
          <T v="label">Health over time</T>
          <T v="caption">{trend}</T>
        </View>
        <View style={s.chart} accessibilityLabel={`Health by visit: ${history.map((h) => status[h.status].label).join(', ')}`}>
          {history.map((h) => (
            <View key={h.id} style={s.col}>
              <View style={{ height: BAR[h.status], alignSelf: 'stretch', borderRadius: 6, backgroundColor: status[h.status].dot }} />
              <T v="caption" style={{ fontSize: 12 }}>{new Date(h.created_at).toLocaleDateString('en-GB', { month: 'short' })}</T>
            </View>
          ))}
        </View>
      </Card>

      <View style={s.facts}>
        {facts.map(([k, v]) => (
          <View key={k} style={s.fact}>
            <T v="caption">{k}</T>
            <T v="label">{v}</T>
          </View>
        ))}
      </View>

      {data.extras && <ServerHealth {...data.extras} only="details" />}

      {latest?.note ? (
        <Card style={{ padding: space.lg, gap: space.xs }}>
          <T v="caption">Latest note</T>
          <T>{latest.note}</T>
        </Card>
      ) : null}

      <Button title="Scan this tree again" icon={ScanLine} onPress={() => router.push('/scan')} />
      <DeleteLink label="Delete this tree" onPress={() => setConfirm(true)} />
      <ConfirmDelete visible={confirm} what="tree" name={tree.id} onCancel={() => setConfirm(false)}
        onConfirm={async () => { await deleteTree(db, tree.id); setConfirm(false); router.back(); }}
        consequences={`${tree.id} and all ${scans.length} of its visits, photos and health records will be completely lost. Its ID is never reused.`} />
    </Screen>
  );
}

// What the server worked out from the observer's checklist, the photos and the ESP32 sensor node.
function ServerHealth({ conditions, sensors, history, only }: TreeExtras & { only: 'causes' | 'details' }) {
  const reading = (icon: LucideIcon, label: string, v: number | null | undefined, unit: string) => (
    <View key={label} style={s.reading}>
      <Icon as={icon} c={color.inkSoft} />
      <View style={{ gap: 2 }}>
        <T v="caption" style={{ fontSize: 12 }}>{label}</T>
        <T v="label">{v == null ? 'N/A' : `${Math.round(v * 10) / 10}${unit}`}</T>
      </View>
    </View>
  );
  const shown = [...conditions].sort((a: Finding, b: Finding) => (a.level === 'unknown' ? 1 : 0) - (b.level === 'unknown' ? 1 : 0));
  if (only === 'causes') {
    return shown.length > 0 ? (
        <View style={{ gap: space.md }}>
          <T v="overline">Possible causes</T>
          <Card>
            {shown.map((c, i) => (
              <Row
                key={c.condition}
                title={c.name}
                sub={c.evidence.slice(0, 2).join(' · ')}
                right={
                  <View style={[s.level, { backgroundColor: LEVEL[c.level].tint }]}>
                    <T v="caption" c={LEVEL[c.level].text} style={{ fontFamily: font.semibold }}>{LEVEL[c.level].label}</T>
                  </View>
                }
                last={i === shown.length - 1}
              />
            ))}
          </Card>
        </View>
    ) : null;
  }
  return (
    <>
      {history.length >= 2 && (
        <Card style={{ padding: space.lg, gap: space.md }}>
          <T v="label">Disease trend by visit</T>
          {CONDITION_KEYS.map((k: ConditionKey) => {
            const vals = history.map((h) => h.c[k]);
            if (vals.every((v) => v == null)) return null;
            const known = vals.filter((v): v is number => v != null);
            const d = known.length >= 2 ? known[known.length - 1] - known[0] : 0;
            return (
              <View key={k} style={{ gap: 4 }}>
                <View style={s.between}>
                  <T v="caption" c={color.ink} style={{ fontFamily: font.medium }}>{CONDITIONS[k].short}</T>
                  <T v="caption" style={{ fontSize: 12 }}>{d > 0.05 ? 'Rising' : d < -0.05 ? 'Falling' : 'Steady'}</T>
                </View>
                <View style={s.spark}>
                  {vals.map((v, i) => (
                    <View key={i} style={{ flex: 1, alignItems: 'center', justifyContent: 'flex-end', height: 28 }}>
                      <View style={{ width: '60%', height: v == null ? 2 : Math.max(2, v * 28), borderRadius: 3, backgroundColor: v == null ? color.line : CONDITIONS[k].color }} />
                    </View>
                  ))}
                </View>
              </View>
            );
          })}
          <View style={s.spark}>
            {history.map((h, i) => <T key={i} v="caption" style={{ flex: 1, textAlign: 'center', fontSize: 10 }}>{new Date(h.at).toLocaleDateString('en-GB', { month: 'short', year: '2-digit' })}</T>)}
          </View>
          <T v="caption" style={{ fontSize: 12 }}>Bar height is how likely the condition was on that visit.</T>
        </Card>
      )}
      <View style={{ gap: space.md }}>
        <T v="overline">Latest sensor reading</T>
        <View style={s.readings}>
          {reading(Droplets, 'Soil moisture', sensors?.soil_moisture_pct, '%')}
          {reading(Thermometer, 'Air temperature', sensors?.air_temp_c, ' °C')}
          {reading(Droplets, 'Humidity', sensors?.humidity_pct, '%')}
          {reading(Sun, 'Light', sensors?.light_lux, ' lx')}
        </View>
        {!sensors && <T v="caption">No ESP32 reading for this tree yet.</T>}
      </View>
    </>
  );
}

const s = StyleSheet.create({
  spark: { flexDirection: 'row', alignItems: 'flex-end' },
  readings: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  reading: { flexBasis: '48%', flexGrow: 1, flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: radius.sm, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  level: { height: 28, paddingHorizontal: 10, borderRadius: radius.pill, justifyContent: 'center' },
  round: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  head: { flexDirection: 'row', alignItems: 'flex-end', gap: space.lg },
  row: { flexDirection: 'row', gap: space.sm },
  fig: { flex: 1, maxWidth: '33%', gap: 6 },
  between: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  chart: { flexDirection: 'row', alignItems: 'flex-end', gap: space.md, height: 88 },
  col: { flex: 1, maxWidth: 48, alignItems: 'center', gap: 6 },
  facts: { flexDirection: 'row', flexWrap: 'wrap', rowGap: space.lg },
  fact: { width: '50%', gap: 2 },
});
