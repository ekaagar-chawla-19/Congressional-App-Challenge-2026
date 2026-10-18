import { router, useLocalSearchParams } from 'expo-router';
import { ChevronRight, MapPin } from '@/icons';
import { Pressable, StyleSheet, View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ago, listTrees, useQuery } from '@/data';
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

  // Frame every tree, with a little margin.
  const lats = trees.map((t) => t.lat!);
  const lngs = trees.map((t) => t.lng!);
  const region = {
    latitude: (Math.min(...lats) + Math.max(...lats)) / 2,
    longitude: (Math.min(...lngs) + Math.max(...lngs)) / 2,
    latitudeDelta: Math.max(Math.max(...lats) - Math.min(...lats), 0.002) * 1.6,
    longitudeDelta: Math.max(Math.max(...lngs) - Math.min(...lngs), 0.002) * 1.6,
  };

  return (
    <View style={{ flex: 1 }}>
      <MapView style={StyleSheet.absoluteFill} initialRegion={region} showsUserLocation showsMyLocationButton>
        {trees.map((t) => {
          const on = t.id === picked?.id;
          return (
            // Keyed on selection so the custom marker re-renders with tracksViewChanges off.
            <Marker key={`${t.id}${on}`} coordinate={{ latitude: t.lat!, longitude: t.lng! }} onPress={() => router.setParams({ sel: t.id })} tracksViewChanges={false}>
              <View style={[s.pin, on && s.pinOn]}>
                <Dot c={status[t.status ?? 'healthy'].dot} size={on ? 20 : 16} />
              </View>
            </Marker>
          );
        })}
      </MapView>

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
  pin: { width: 36, height: 36, borderRadius: radius.pill, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  pinOn: { width: 44, height: 44, borderWidth: 2, borderColor: color.ink },
  legend: { position: 'absolute', left: space.xl, flexDirection: 'row', gap: space.sm },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 28, paddingHorizontal: 10, borderRadius: radius.pill, backgroundColor: color.card },
  sheet: { position: 'absolute', left: space.lg, right: space.lg, bottom: space.lg, flexDirection: 'row', alignItems: 'center', gap: space.lg, padding: space.lg, borderRadius: radius.lg, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, shadowColor: color.ink, shadowOpacity: 0.1, shadowRadius: 12, shadowOffset: { width: 0, height: 8 }, elevation: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  go: { width: 44, height: 44, borderRadius: radius.sm, backgroundColor: color.spruce, alignItems: 'center', justifyContent: 'center' },
});
