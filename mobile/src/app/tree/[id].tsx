import { router, useLocalSearchParams } from 'expo-router';
import { MapPin, ScanLine } from '@/icons';
import { Pressable, StyleSheet, View } from 'react-native';
import { fmtDate, getTree, useQuery } from '@/data';
import { color, radius, space, status, type Status } from '@/theme';
import { BackBar, Badge, Button, Card, Icon, Photo, Screen, T } from '@/ui';

const BAR: Record<Status, number> = { healthy: 20, watch: 40, infested: 64 };

export default function TreeDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useQuery((db) => getTree(db, id), id);
  if (!data?.tree) return <Screen>{data ? <BackBar title="Tree not found" /> : null}</Screen>;

  const { tree, scans } = data;
  const latest = scans[0];
  const shots = scans.map((sc) => ({ at: sc.created_at, uri: (JSON.parse(sc.photos) as string[])[0] })).slice(0, 3);
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

      {latest?.note ? (
        <Card style={{ padding: space.lg, gap: space.xs }}>
          <T v="caption">Latest note</T>
          <T>{latest.note}</T>
        </Card>
      ) : null}

      <Button title="Scan this tree again" icon={ScanLine} onPress={() => router.push('/scan')} />
    </Screen>
  );
}

const s = StyleSheet.create({
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
