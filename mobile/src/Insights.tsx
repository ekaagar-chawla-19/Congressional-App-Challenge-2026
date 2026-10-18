import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';
import * as api from './api';
import { CONDITIONS, CONDITION_KEYS } from './conditions';
import { BookmarkPlus, ChevronRight, Droplets, Flame, Lightbulb, MapPin, Sun, Thermometer, Trash, TrendingDown, TrendingUp, type LucideIcon } from './icons';
import { shortName, useSession } from './session';
import { color, font, radius, space, status } from './theme';
import { BackBar, Button, Card, Dot, Empty, Icon, IconBox, Row, Screen, SectionHead, T, notify } from './ui';

export type Scope = { kind: 'forest' } | { kind: 'section'; id: number } | { kind: 'area'; bbox: api.Bbox };

const sevLabel = (x: number | null) => (x == null ? 'N/A' : x < 0.5 ? 'Healthy' : x < 1.5 ? 'Light' : x < 2.5 ? 'Moderate' : 'Severe');
const sevStatus = (x: number | null) => (x == null ? 'unrated' : x < 0.5 ? 'healthy' : x < 1.5 ? 'watch' : 'infested') as keyof typeof status;

// Analysis of the whole forest, one section, or an area picked on the map: tree health, how common each
// condition is, where each is worst (hotspots), how things changed over time, and what to do.
export default function Insights({ scope, tabbed }: { scope: Scope; tabbed?: boolean }) {
  const forest = useSession((s) => s.forest);
  const [a, setA] = useState<api.Analysis>();
  const [error, setError] = useState<string>();
  const key = JSON.stringify(scope) + forest?.id;
  const load = useCallback(() => {
    const p = scope.kind === 'section' ? api.sectionAnalysis(scope.id) : api.analysis(scope.kind === 'area' ? scope.bbox : undefined);
    return p.then(setA, (e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => void load(), [load]);

  const title = scope.kind === 'forest' ? shortName(forest?.name ?? 'Forest') : scope.kind === 'section' ? a?.section?.name ?? 'Section' : 'Selected area';
  const head = (
    <>
      {tabbed ? null : <BackBar title={scope.kind === 'forest' ? 'Forest' : scope.kind === 'section' ? 'Section' : 'Map area'} />}
      <View style={{ gap: 2 }}>
        <T v="caption">{scope.kind === 'forest' ? 'Forest insights' : scope.kind === 'section' ? `Section of ${shortName(forest?.name ?? '')}` : `Area of ${shortName(forest?.name ?? '')}`}</T>
        <T v="display">{title}</T>
      </View>
    </>
  );

  if (error) return <Screen scroll tabbed={tabbed}>{head}<Empty icon={ChevronRight} title="Could not load" body={error} /></Screen>;
  if (!a) return <Screen tabbed={tabbed}>{head}<ActivityIndicator color={color.spruce} style={{ marginTop: space.xxl }} /></Screen>;

  const sm = a.summary;
  if (sm.trees === 0) {
    return (
      <Screen scroll tabbed={tabbed}>
        {head}
        <Empty icon={MapPin} title="No trees here" body="Zoom or move the map to an area with hemlocks and analyze again." />
      </Screen>
    );
  }

  return (
    <Screen scroll tabbed={tabbed}>
      {head}
      <View style={s.tiles}>
        <Tile value={String(sm.trees)} label="Hemlocks" />
        <Tile value={sm.pct_moderate_or_severe == null ? 'N/A' : `${Math.round(sm.pct_moderate_or_severe)}%`} label="Moderate or severe" tone={status.infested.text} />
        <Tile value={sm.mean_severity == null ? 'N/A' : `${sm.mean_severity.toFixed(1)}`} label={`Avg. severity (0-3): ${sevLabel(sm.mean_severity).toLowerCase()}`} tone={status[sevStatus(sm.mean_severity)].text} />
      </View>

      <Diseases a={a} />
      <Hotspots a={a} />
      <Trends trends={a.trends} />
      {scope.kind === 'forest' && <Sections sections={a.sections} reload={load} />}
      {scope.kind === 'area' && <SaveSection bbox={scope.bbox} />}
      <WorstTrees a={a} />
      <Sensors means={sm.sensor_means} n={sm.trees_with_sensor_data} trees={sm.trees} />
      <Advice a={a} />
      {scope.kind === 'section' && a.section && <DeleteSection id={a.section.section_id} name={a.section.name} />}
    </Screen>
  );
}

const Tile = ({ value, label, tone }: { value: string; label: string; tone?: string }) => (
  <View style={s.tile}>
    <T v="display" c={tone ?? color.ink} style={{ fontSize: 24, lineHeight: 30 }} numberOfLines={1}>{value}</T>
    <T v="caption">{label}</T>
  </View>
);

function Diseases({ a }: { a: api.Analysis }) {
  const n = a.summary.trees;
  return (
    <View style={{ gap: space.md }}>
      <SectionHead title="Diseases" action="Guide" onAction={() => router.push('/about')} />
      <Card style={{ padding: space.lg, gap: space.lg }}>
        {CONDITION_KEYS.map((k) => {
          const c = a.summary.conditions[k];
          const top = a.summary.most_prominent_condition === k;
          return (
            <Pressable key={k} style={{ gap: space.sm }} onPress={() => router.navigate(`/map?layer=${k}`)} accessibilityRole="button" accessibilityLabel={`Show ${CONDITIONS[k].short} on the map`}>
              <View style={s.between}>
                <View style={s.inline}>
                  <Dot c={CONDITIONS[k].color} />
                  <T v="label">{CONDITIONS[k].short}</T>
                  {top && <View style={[s.pill, { backgroundColor: CONDITIONS[k].tint }]}><T v="caption" c={CONDITIONS[k].color} style={{ fontSize: 11, fontFamily: font.semibold }}>Most common</T></View>}
                </View>
                <T v="caption">{`${c.likely + c.possible} of ${n} trees`}</T>
              </View>
              <View style={s.track}>
                <View style={{ flex: c.likely, backgroundColor: CONDITIONS[k].color }} />
                <View style={{ flex: c.possible, backgroundColor: CONDITIONS[k].color + '70' }} />
                <View style={{ flex: Math.max(n - c.likely - c.possible, 0) }} />
              </View>
              <T v="caption" style={{ fontSize: 12 }}>{`${c.likely} likely · ${c.possible} possible · ${c.assessed} assessed`}</T>
            </Pressable>
          );
        })}
      </Card>
    </View>
  );
}

function Hotspots({ a }: { a: api.Analysis }) {
  const rows = CONDITION_KEYS.map((k) => [k, a.hotspots[k]?.[0]] as const).filter(([, h]) => h);
  if (!rows.length) return null;
  return (
    <View style={{ gap: space.md }}>
      <SectionHead title="Where each is worst" />
      <Card>
        {rows.map(([k, h], i) => (
          <Row key={k} left={<IconBox icon={Flame} bg={CONDITIONS[k].tint} fg={CONDITIONS[k].color} />}
            title={CONDITIONS[k].short}
            sub={`${h!.affected} of ${h!.trees} trees in a 150 m patch (${h!.tree_ids.slice(0, 3).join(', ')}${h!.tree_ids.length > 3 ? '…' : ''})`}
            onPress={() => router.navigate(`/map?layer=${k}`)} last={i === rows.length - 1} />
        ))}
      </Card>
    </View>
  );
}

// Per quarter: share of visits rated moderate/severe, and per condition the share of assessed visits where it showed.
function Trends({ trends }: { trends: api.Trend[] }) {
  // Quarters with only a handful of visits swing wildly; leave them out of the chart.
  const ts = trends.filter((t) => t.visits >= 5).slice(-8);
  if (ts.length < 2) return null;
  const first = ts.find((t) => t.pct_moderate_or_severe != null);
  const last = [...ts].reverse().find((t) => t.pct_moderate_or_severe != null);
  const delta = first && last ? last.pct_moderate_or_severe! - first.pct_moderate_or_severe! : 0;
  const bars = (vals: (number | null)[], c: string, h = 56) => (
    <View style={[s.bars, { height: h }]}>
      {vals.map((v, i) => (
        <View key={i} style={{ flex: 1, alignItems: 'center', justifyContent: 'flex-end', height: h }}>
          <View style={{ width: '70%', height: v == null ? 2 : Math.max(2, (v / 100) * h), borderRadius: 3, backgroundColor: v == null ? color.line : c }} />
        </View>
      ))}
    </View>
  );
  const change = (vals: (number | null)[]) => {
    const v = vals.filter((x): x is number => x != null);
    return v.length < 2 ? null : Math.round(v[v.length - 1] - v[0]);
  };
  return (
    <View style={{ gap: space.md }}>
      <SectionHead title="Trends" />
      <Card style={{ padding: space.lg, gap: space.lg }}>
        <View style={s.between}>
          <T v="label">Moderate or severe</T>
          <View style={s.inline}>
            <Icon as={delta > 0 ? TrendingUp : TrendingDown} c={delta > 0 ? status.infested.text : status.healthy.text} />
            <T v="caption" c={delta > 0 ? status.infested.text : status.healthy.text} style={{ fontFamily: font.semibold }}>
              {`${delta > 0 ? '+' : ''}${Math.round(delta)} pts since ${first?.period}`}
            </T>
          </View>
        </View>
        {bars(ts.map((t) => t.pct_moderate_or_severe), status.infested.dot, 72)}
        <View style={s.bars}>
          {ts.map((t) => <T key={t.period} v="caption" style={{ flex: 1, textAlign: 'center', fontSize: 10, lineHeight: 13 }}>{`${t.period.slice(5)}\n'${t.period.slice(2, 4)}`}</T>)}
        </View>
        {CONDITION_KEYS.map((k) => {
          const vals = ts.map((t) => t.conditions[k]?.pct ?? null);
          const d = change(vals);
          return (
            <View key={k} style={{ gap: space.xs }}>
              <View style={s.between}>
                <View style={s.inline}><Dot c={CONDITIONS[k].color} /><T v="caption" c={color.ink} style={{ fontFamily: font.medium }}>{CONDITIONS[k].short}</T></View>
                <T v="caption" style={{ fontSize: 12 }}>{d == null ? 'not enough data' : `${d > 0 ? '+' : ''}${d} pts`}</T>
              </View>
              {bars(vals, CONDITIONS[k].color, 32)}
            </View>
          );
        })}
        <T v="caption" style={{ fontSize: 12 }}>Share of visits each quarter (quarters with fewer than 5 visits are left out).</T>
      </Card>
    </View>
  );
}

function Sections({ sections }: { sections: api.Section[]; reload: () => void }) {
  return (
    <View style={{ gap: space.md }}>
      <SectionHead title="Sections" action="Draw on map" onAction={() => router.navigate('/map')} />
      {sections.length === 0 ? (
        <Card><Empty icon={MapPin} title="No sections yet" body="On the map, frame an area, tap Analyze this view, then Save as section." /></Card>
      ) : (
        <Card>
          {[...sections].sort((x, y) => (y.stress_score ?? 0) - (x.stress_score ?? 0)).map((sec, i) => {
            const ds = CONDITION_KEYS.filter((k) => sec.condition_counts[k]).map((k) => `${CONDITIONS[k].tiny} ${sec.condition_counts[k]}`);
            return (
              <Row key={sec.section_id} title={sec.name}
                sub={`${sec.trees} trees · ${sec.pct_moderate_or_severe == null ? 'not rated' : `${Math.round(sec.pct_moderate_or_severe)}% moderate+`}${ds.length ? ` · ${ds.join(', ')}` : ''}`}
                left={<View style={[s.stress, { backgroundColor: status[sevStatus(sec.mean_severity)].tint }]}><T v="label" c={status[sevStatus(sec.mean_severity)].text} style={{ fontSize: 13 }}>{sec.mean_severity == null ? '–' : sec.mean_severity.toFixed(1)}</T></View>}
                onPress={() => router.push(`/area?section=${sec.section_id}`)} last={i === sections.length - 1} />
            );
          })}
        </Card>
      )}
    </View>
  );
}

function SaveSection({ bbox }: { bbox: api.Bbox }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const sec = await api.createSection(name.trim(), bbox);
      router.replace(`/area?section=${sec.section_id}`);
    } catch (e) {
      notify('Could not save', (e as Error).message);
      setBusy(false);
    }
  };
  return (
    <Card style={{ padding: space.lg, gap: space.md }}>
      <View style={s.inline}><Icon as={BookmarkPlus} c={color.spruce} /><T v="label">Save this area as a section</T></View>
      <TextInput value={name} onChangeText={setName} placeholder="Section name, e.g. Campground loop" placeholderTextColor={color.inkSoft} style={s.input} onSubmitEditing={save} />
      <Button title={busy ? 'Saving' : 'Save section'} onPress={save} disabled={busy || !name.trim()} />
    </Card>
  );
}

function DeleteSection({ id, name }: { id: number; name: string }) {
  const del = async () => {
    await api.deleteSection(id).catch(() => {});
    router.back();
  };
  return (
    <Pressable onPress={del} style={[s.inline, { alignSelf: 'center', padding: space.md }]} accessibilityRole="button">
      <Icon as={Trash} c={color.inkSoft} />
      <T v="label" c={color.inkSoft}>{`Delete section "${name}"`}</T>
    </Pressable>
  );
}

function WorstTrees({ a }: { a: api.Analysis }) {
  const ws = a.worst_trees.slice(0, 5);
  if (!ws.length) return null;
  return (
    <View style={{ gap: space.md }}>
      <SectionHead title="Trees that need attention" />
      <Card>
        {ws.map((t, i) => (
          <Row key={t.tree_id} title={<T v="id">{t.tree_id}</T>}
            sub={`${sevLabel(t.severity)}${t.main_condition ? ` · ${CONDITIONS[t.main_condition].short}` : ''} · stress ${Math.round(t.stress_score * 100)}`}
            left={<View style={[s.stress, { backgroundColor: status[sevStatus(t.severity)].tint }]}><T v="label" c={status[sevStatus(t.severity)].text} style={{ fontSize: 13 }}>{Math.round(t.stress_score * 100)}</T></View>}
            onPress={() => router.push(`/tree/${t.tree_id}`)} last={i === ws.length - 1} />
        ))}
      </Card>
    </View>
  );
}

function Sensors({ means, n, trees }: { means: api.Analysis['summary']['sensor_means']; n: number; trees: number }) {
  const r = (icon: LucideIcon, label: string, k: string, unit: string) => (
    <View key={k} style={s.reading}>
      <Icon as={icon} c={color.inkSoft} />
      <View style={{ gap: 2 }}>
        <T v="caption" style={{ fontSize: 12 }}>{label}</T>
        <T v="label">{means[k] ? `${means[k]!.mean}${unit}` : 'N/A'}</T>
      </View>
    </View>
  );
  return (
    <View style={{ gap: space.md }}>
      <SectionHead title="Sensor averages" />
      <View style={s.readings}>
        {r(Droplets, 'Soil moisture', 'soil_moisture_pct', '%')}
        {r(Thermometer, 'Air temperature', 'air_temp_c', ' °C')}
        {r(Droplets, 'Humidity', 'humidity_pct', '%')}
        {r(Sun, 'Light', 'light_lux', ' lx')}
      </View>
      <T v="caption">{`Latest ESP32 reading of ${n} of ${trees} trees.`}</T>
    </View>
  );
}

function Advice({ a }: { a: api.Analysis }) {
  const recs = a.summary.recommendations;
  if (!recs.length) return null;
  return (
    <View style={{ gap: space.md }}>
      <SectionHead title="What to do" />
      {recs.map((r) => {
        const k = r.condition as api.ConditionKey;
        return (
          <Card key={r.condition} style={{ padding: space.lg, gap: space.sm }}>
            <View style={s.inline}>
              <Icon as={Lightbulb} c={CONDITIONS[k]?.color ?? color.spruce} />
              <T v="label" style={{ flex: 1 }}>{`${CONDITIONS[k]?.short ?? r.name} · ${r.trees_affected} trees`}</T>
            </View>
            {r.steps.slice(0, 3).map((x) => <T key={x} v="caption" c={color.ink} style={{ fontSize: 13, lineHeight: 19 }}>{`• ${x}`}</T>)}
          </Card>
        );
      })}
      <T v="caption" style={{ fontSize: 12 }}>{a.summary.general_advice?.[1]}</T>
    </View>
  );
}

const s = StyleSheet.create({
  tiles: { flexDirection: 'row', gap: space.sm },
  tile: { flex: 1, gap: 2, padding: space.md, borderRadius: radius.md, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm },
  inline: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  pill: { paddingHorizontal: 8, height: 20, borderRadius: radius.pill, justifyContent: 'center' },
  track: { flexDirection: 'row', height: 10, borderRadius: radius.pill, overflow: 'hidden', backgroundColor: color.lineSoft },
  bars: { flexDirection: 'row', alignItems: 'flex-end' },
  stress: { width: 44, height: 44, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  input: { minHeight: 48, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.paper, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink },
  readings: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  reading: { flexBasis: '48%', flexGrow: 1, flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: radius.sm, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
});
