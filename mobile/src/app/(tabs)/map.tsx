import { router, useLocalSearchParams } from 'expo-router';
import { ChartColumn, ChevronRight, MapPin, SquareDashed } from '@/icons';
import { useCallback, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as api from '@/api';
import { CONDITIONS, CONDITION_KEYS, likelihoodColor, type Layer } from '@/conditions';
import { ago, listTrees, useQuery } from '@/data';
import MapCanvas from '@/MapCanvas';
import { isServer, useSession } from '@/session';
import { color, font, radius, space, status } from '@/theme';
import { Badge, Dot, Empty, Icon, Screen, T } from '@/ui';

const LAYERS: { key: Layer; label: string }[] = [{ key: 'health', label: 'Health' }, ...CONDITION_KEYS.map((k) => ({ key: k, label: CONDITIONS[k].short }))];

// Landmarks, sections and disease hotspots come from the server; the offline demo shows trees only.
const extras = async () => {
  if (!isServer()) return { landmarks: [], sections: [], hotspots: {} as api.Analysis['hotspots'] };
  const [landmarks, a] = await Promise.all([api.landmarks(), api.analysis()]);
  return { landmarks, sections: a.sections, hotspots: a.hotspots };
};

export default function TreeMap() {
  const { top } = useSafeAreaInsets();
  const trees = (useQuery(listTrees) ?? []).filter((t) => t.lat != null && t.lng != null);
  const more = useQuery(extras);
  const server = useSession((s) => s.mode === 'server');
  const { sel, layer: layerParam } = useLocalSearchParams<{ sel?: string; layer?: Layer }>();
  const [layer, setLayer] = useState<Layer>(layerParam ?? 'health');
  const [showSections, setShowSections] = useState(true);
  const picked = trees.find((t) => t.id === sel);
  const viewBox = useRef<api.Bbox | null>(null);
  const onView = useCallback((b: api.Bbox) => void (viewBox.current = b), []);

  if (!trees.length) {
    return (
      <Screen tabbed>
        <T v="display">Map</T>
        <Empty icon={MapPin} title="Nothing to map yet" body="Trees you register with location turned on will appear here." />
      </Screen>
    );
  }

  const analyzeView = () => {
    const b = viewBox.current;
    if (b) router.push(`/area?bbox=${b.map((v) => v.toFixed(6)).join(',')}`);
  };
  const legend: [string, string][] = layer === 'health'
    ? (['healthy', 'watch', 'infested', 'unrated'] as const).map((k) => [status[k].dot, status[k].label])
    : [[likelihoodColor(layer, 0.8), 'Likely'], [likelihoodColor(layer, 0.45), 'Possible'], [likelihoodColor(layer, 0.1), 'Unlikely']];

  return (
    <View style={{ flex: 1 }}>
      <MapCanvas trees={trees} landmarks={more?.landmarks ?? []} sections={more?.sections ?? []} showSections={showSections}
        hotspots={layer === 'health' ? [] : more?.hotspots[layer] ?? []} layer={layer} selected={picked?.id}
        onSelect={(id) => router.setParams({ sel: id })} onView={onView} />

      <View style={[s.top, { top: top + space.sm }]}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm, paddingHorizontal: space.lg }}>
          {LAYERS.map((l) => {
            const on = l.key === layer;
            return (
              <Pressable key={l.key} onPress={() => setLayer(l.key)} accessibilityRole="tab" accessibilityState={{ selected: on }} style={[s.chip, on && s.chipOn]}>
                {l.key !== 'health' && <Dot c={CONDITIONS[l.key].color} />}
                <T v="caption" c={on ? color.paper : color.ink} style={{ fontFamily: font.semibold }}>{l.label}</T>
              </Pressable>
            );
          })}
        </ScrollView>
        <View style={s.legendRow}>
          {legend.map(([c, label]) => (
            <View key={label} style={s.legendItem}>
              <Dot c={c} />
              <T v="caption" c={color.ink} style={{ fontSize: 11, fontFamily: font.medium }}>{label}</T>
            </View>
          ))}
          {layer !== 'health' && (more?.hotspots[layer]?.length ?? 0) > 0 && (
            <View style={s.legendItem}>
              <View style={{ width: 12, height: 10, borderWidth: 2, borderColor: CONDITIONS[layer].color, borderRadius: 2 }} />
              <T v="caption" c={color.ink} style={{ fontSize: 11, fontFamily: font.medium }}>Hotspot</T>
            </View>
          )}
        </View>
      </View>

      <View style={s.bottom}>
        {server && (
          <View style={s.actions}>
            <Pressable style={s.action} onPress={analyzeView} accessibilityRole="button">
              <Icon as={ChartColumn} c={color.paper} />
              <T v="label" c={color.paper} style={{ fontSize: 14 }}>Analyze this view</T>
            </Pressable>
            <Pressable style={[s.action, s.actionSoft, showSections && { borderColor: color.spruce }]} onPress={() => setShowSections(!showSections)} accessibilityRole="switch" accessibilityState={{ checked: showSections }}>
              <Icon as={SquareDashed} c={color.spruce} />
              <T v="label" c={color.spruce} style={{ fontSize: 14 }}>Sections</T>
            </Pressable>
          </View>
        )}
        {picked && (
          <Pressable style={s.sheet} onPress={() => router.push(`/tree/${picked.id}`)} accessibilityRole="button" accessibilityLabel={`Open ${picked.id}`}>
            <View style={{ flex: 1, gap: space.xs }}>
              <View style={s.row}>
                <T v="id" style={{ fontSize: 22 }}>{picked.id}</T>
                {picked.status && <Badge s={picked.status} />}
              </View>
              <T v="caption">{`${picked.place} · scanned ${ago(picked.last_scan).toLowerCase()}`}</T>
            </View>
            <View style={s.go}>
              <Icon as={ChevronRight} c={color.paper} />
            </View>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  top: { position: 'absolute', left: 0, right: 0, gap: space.sm },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 34, paddingHorizontal: 12, borderRadius: radius.pill, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  chipOn: { backgroundColor: color.spruce, borderColor: color.spruce },
  legendRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, paddingHorizontal: space.lg },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5, height: 24, paddingHorizontal: 8, borderRadius: radius.pill, backgroundColor: 'rgba(255,255,255,0.9)' },
  bottom: { position: 'absolute', left: space.lg, right: space.lg, bottom: space.lg, gap: space.sm },
  actions: { flexDirection: 'row', gap: space.sm },
  action: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: space.sm, height: 48, borderRadius: radius.md, backgroundColor: color.spruce },
  actionSoft: { flex: 0, minWidth: 128, paddingHorizontal: space.lg, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  sheet: { flexDirection: 'row', alignItems: 'center', gap: space.lg, padding: space.lg, borderRadius: radius.lg, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, shadowColor: color.ink, shadowOpacity: 0.1, shadowRadius: 12, shadowOffset: { width: 0, height: 8 }, elevation: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  go: { width: 44, height: 44, borderRadius: radius.sm, backgroundColor: color.spruce, alignItems: 'center', justifyContent: 'center' },
});
