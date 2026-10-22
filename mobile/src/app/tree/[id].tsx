import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useDb } from '@/db';
import { useCallback, useState } from 'react';
import { ArrowRight, Cpu, MapPin, ScanLine } from '@/icons';
import { Pressable, StyleSheet, View } from 'react-native';
import type { ConditionKey, Finding } from '@/api';
import { CONDITIONS, CONDITION_KEYS } from '@/conditions';
import { deleteTree, fmtDate, getTree, useQuery, type TreeExtras } from '@/data';
import { LoadError } from '@/LoadError';
import { SensorTiles, sensorLine } from '@/SensorPanel';
import { hasAny, useConnected } from '@/sensors';
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
  // Reload when coming back from adding a reading or a scan.
  const [rev, setRev] = useState(0);
  useFocusEffect(useCallback(() => setRev((r) => r + 1), []));
  const data = useQuery((db) => getTree(db, id), `${id}:${rev}`);
  const [confirm, setConfirm] = useState(false);
  const connected = useConnected();
  if (!data?.tree) return <Screen><BackBar title={data ? 'Tree not found' : id} /><LoadError /></Screen>;

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
      {data.extras && <ServerHealth {...data.extras} only="twin" />}

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
      {connected && <Button title="Add sensor reading" icon={Cpu} secondary onPress={() => router.push({ pathname: '/reading', params: { id: tree.id } })} />}
      <DeleteLink label="Delete this tree" onPress={() => setConfirm(true)} />
      <ConfirmDelete visible={confirm} what="tree" name={tree.id} onCancel={() => setConfirm(false)}
        onConfirm={async () => { await deleteTree(db, tree.id); setConfirm(false); router.back(); }}
        consequences={`${tree.id} and all ${scans.length} of its visits, photos and health records will be completely lost. Its ID is never reused.`} />
    </Screen>
  );
}

// What the diagnosis (server, or the phone in phone-only mode) worked out from the checklist, photos and sensors.
function ServerHealth({ conditions, sensors, history, readings, environment, changes, next, only }: TreeExtras & { only: 'causes' | 'twin' | 'details' }) {
  const [all, setAll] = useState(false); // sensor history: the latest 3, or every reading
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
  if (only === 'twin') {
    return changes.length > 0 || next ? (
      <Card style={{ padding: space.lg, gap: space.md }}>
        {changes.length > 0 && (
          <View style={{ gap: space.xs }}>
            <T v="label">Since last visit</T>
            {changes.map((c) => <T key={c} c={color.inkSoft}>{`• ${c}`}</T>)}
          </View>
        )}
        {next && (
          <View style={[s.next, changes.length > 0 && s.rule]}>
            <Icon as={ArrowRight} c={color.spruce} />
            <View style={{ flex: 1, gap: 2 }}>
              <T v="caption">Next action</T>
              <T v="label">{next}</T>
            </View>
          </View>
        )}
      </Card>
    ) : null;
  }
  const shownReadings = all ? readings : readings.slice(0, 3);
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
      {/* Only for trees with sensor data, and only the sensors that were measured: the hardware is optional. */}
      {hasAny(sensors) && (
      <View style={{ gap: space.md }}>
        <T v="overline">Latest sensor reading</T>
        <SensorTiles sensors={sensors} />
        {environment && (
          <Card style={{ padding: space.lg, gap: space.xs }}>
            <T v="label">{environment.summary}</T>
            {environment.changes.map((c) => <T key={c} v="caption">{c}</T>)}
          </Card>
        )}
      </View>
      )}
      {readings.length > 0 && (
        <View style={{ gap: space.md }}>
          <T v="overline">Sensor history</T>
          <Card>
            {shownReadings.map((r, i) => (
              <Row key={r.observation_id} title={fmtDate(Date.parse(r.timestamp))}
                sub={`${sensorLine(r.sensors)}${r.vpd_kpa != null ? ` · VPD ${r.vpd_kpa.toFixed(1)} kPa` : ''}`}
                last={i === shownReadings.length - 1 && readings.length <= 3} />
            ))}
            {readings.length > 3 && (
              <Pressable onPress={() => setAll(!all)} accessibilityRole="button" style={s.more}>
                <T v="label" c={color.spruce}>{all ? 'Show less' : `See all ${readings.length} readings`}</T>
              </Pressable>
            )}
          </Card>
        </View>
      )}
    </>
  );
}

const s = StyleSheet.create({
  spark: { flexDirection: 'row', alignItems: 'flex-end' },
  next: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  rule: { paddingTop: space.md, borderTopWidth: 1, borderTopColor: color.lineSoft },
  more: { padding: space.lg, alignItems: 'center' },
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
