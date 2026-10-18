import { router, useLocalSearchParams } from 'expo-router';
import { ChevronRight, MapPin } from '@/icons';
import { Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ago, listTrees, useQuery } from '@/data';
import MapCanvas from '@/MapCanvas';
import { color, font, radius, space, status } from '@/theme';
import { Badge, Dot, Empty, Icon, Screen, T } from '@/ui';

export default function TreeMap() {
  const { top } = useSafeAreaInsets();
  const trees = (useQuery(listTrees) ?? []).filter((t) => t.lat != null && t.lng != null);
  const { sel } = useLocalSearchParams<{ sel?: string }>();
  const picked = trees.find((t) => t.id === sel) ?? trees[0];

  if (!trees.length) {
    return (
      <Screen tabbed>
        <T v="display">Map</T>
        <Empty icon={MapPin} title="Nothing to map yet" body="Trees you register with location turned on will appear here." />
      </Screen>
    );
  }

  return (
    <View style={{ flex: 1 }}>
      <MapCanvas trees={trees} selected={picked?.id} onSelect={(id) => router.setParams({ sel: id })} />

      <View style={[s.legend, { top: top + space.lg }]} pointerEvents="none">
        {(Object.keys(status) as (keyof typeof status)[]).map((k) => (
          <View key={k} style={s.legendItem}>
            <Dot c={status[k].dot} />
            <T v="caption" c={color.ink} style={{ fontFamily: font.medium, fontSize: 12 }}>{status[k].label}</T>
          </View>
        ))}
      </View>

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
  );
}

const s = StyleSheet.create({
  legend: { position: 'absolute', left: space.lg, right: space.lg, flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 28, paddingHorizontal: 10, borderRadius: radius.pill, backgroundColor: color.card },
  sheet: { position: 'absolute', left: space.lg, right: space.lg, bottom: space.lg, flexDirection: 'row', alignItems: 'center', gap: space.lg, padding: space.lg, borderRadius: radius.lg, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, shadowColor: color.ink, shadowOpacity: 0.1, shadowRadius: 12, shadowOffset: { width: 0, height: 8 }, elevation: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  go: { width: 44, height: 44, borderRadius: radius.sm, backgroundColor: color.spruce, alignItems: 'center', justifyContent: 'center' },
});
