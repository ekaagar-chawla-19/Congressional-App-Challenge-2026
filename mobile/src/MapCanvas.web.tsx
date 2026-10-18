import { Pressable, StyleSheet, View } from 'react-native';
import type { MapProps } from './MapCanvas';
import { color, radius, status } from './theme';
import { Dot, T } from './ui';

// Browser version of the map (react-native-maps is native only): trees placed by their GPS
// position on a plain field, with a scale bar. Same pins and selection as on the phone.
export default function MapCanvas({ trees, selected, onSelect }: MapProps) {
  const lats = trees.map((t) => t.lat!);
  const lngs = trees.map((t) => t.lng!);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const kx = 111_320 * Math.cos((midLat * Math.PI) / 180); // metres per degree of longitude
  const w = Math.max((Math.max(...lngs) - Math.min(...lngs)) * kx, 100);
  const h = Math.max((Math.max(...lats) - Math.min(...lats)) * 111_320, 100);
  const span = Math.max(w, h) * 1.25;
  const x = (lng: number) => 50 + (((lng - (Math.min(...lngs) + Math.max(...lngs)) / 2) * kx) / span) * 100;
  const y = (lat: number) => 46 - (((lat - midLat) * 111_320) / span) * 100;
  const bar = [50, 100, 200, 500, 1000].find((m) => m / span > 0.15) ?? 1000;

  return (
    <View style={s.field}>
      {[20, 40, 60, 80].map((p) => <View key={`v${p}`} style={[s.grid, { left: `${p}%`, top: 0, bottom: 0, width: 1 }]} />)}
      {[20, 40, 60, 80].map((p) => <View key={`h${p}`} style={[s.grid, { top: `${p}%`, left: 0, right: 0, height: 1 }]} />)}
      <View style={s.square}>
        {trees.map((t) => {
          const on = t.id === selected;
          return (
            <Pressable key={t.id} onPress={() => onSelect(t.id)} accessibilityLabel={`${t.id}, ${status[t.status ?? 'unrated'].label}`}
              style={[s.pin, on && s.pinOn, { left: `${x(t.lng!)}%`, top: `${y(t.lat!)}%`, zIndex: on ? 2 : 1 }]}>
              <Dot c={status[t.status ?? 'unrated'].dot} size={on ? 18 : 14} />
            </Pressable>
          );
        })}
      </View>
      <View style={s.scale}>
        <View style={{ width: `${(bar / span) * 100}%`, minWidth: 40, height: 4, backgroundColor: color.ink, borderRadius: 2 }} />
        <T v="caption" c={color.ink} style={{ fontSize: 12 }}>{bar >= 1000 ? `${bar / 1000} km` : `${bar} m`}</T>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  field: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#DCE5D6', overflow: 'hidden' },
  grid: { position: 'absolute', backgroundColor: 'rgba(30, 59, 50, 0.08)' },
  square: { position: 'absolute', left: 0, right: 0, top: 70, bottom: 120 },
  pin: { position: 'absolute', width: 30, height: 30, marginLeft: -15, marginTop: -15, borderRadius: radius.pill, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  pinOn: { width: 38, height: 38, marginLeft: -19, marginTop: -19, borderWidth: 2, borderColor: color.ink },
  scale: { position: 'absolute', left: 24, bottom: 132, width: '40%', gap: 4 },
});
