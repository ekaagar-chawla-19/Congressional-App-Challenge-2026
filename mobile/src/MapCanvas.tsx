import { useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import MapView, { Marker, Polygon, Polyline, type Region } from 'react-native-maps';
import { Minus, Plus, Scan as Fit } from './icons';
import { hotspotColor, LANDMARK_STYLE, pinColor, type MapProps } from './mapTypes';
import { color, font, radius } from './theme';
import { Dot, Icon, T } from './ui';

export type { MapProps } from './mapTypes';

const rect = ([w, s, e, n]: number[]) => [
  { latitude: s, longitude: w }, { latitude: s, longitude: e }, { latitude: n, longitude: e }, { latitude: n, longitude: w },
];

export default function MapCanvas({ trees, landmarks, sections, showSections, hotspots, layer, selected, onSelect, onView }: MapProps) {
  const map = useRef<MapView>(null);
  const [satellite, setSatellite] = useState(false);
  // Frame every tree, with a little margin.
  const lats = trees.map((t) => t.lat!);
  const lngs = trees.map((t) => t.lng!);
  const home: Region = {
    latitude: (Math.min(...lats) + Math.max(...lats)) / 2,
    longitude: (Math.min(...lngs) + Math.max(...lngs)) / 2,
    latitudeDelta: Math.max(Math.max(...lats) - Math.min(...lats), 0.002) * 1.4,
    longitudeDelta: Math.max(Math.max(...lngs) - Math.min(...lngs), 0.002) * 1.4,
  };
  const region = useRef(home);
  const zoom = (f: number) => {
    const r = region.current;
    map.current?.animateToRegion({ ...r, latitudeDelta: r.latitudeDelta * f, longitudeDelta: r.longitudeDelta * f }, 250);
  };
  const changed = (r: Region) => {
    region.current = r;
    onView([r.longitude - r.longitudeDelta / 2, r.latitude - r.latitudeDelta / 2, r.longitude + r.longitudeDelta / 2, r.latitude + r.latitudeDelta / 2]);
  };

  return (
    <View style={StyleSheet.absoluteFill}>
      <MapView ref={map} style={StyleSheet.absoluteFill} initialRegion={home} onRegionChangeComplete={changed} onMapReady={() => changed(home)}
        showsUserLocation mapType={satellite ? 'hybrid' : 'standard'}>
        {landmarks.map((l) => {
          if (l.geometry.type === 'LineString') {
            const st = LANDMARK_STYLE[l.properties.kind as keyof typeof LANDMARK_STYLE] ?? LANDMARK_STYLE.trail;
            return (
              <Polyline key={l.properties.name} coordinates={l.geometry.coordinates.map(([lo, la]) => ({ latitude: la, longitude: lo }))}
                strokeColor={st.color} strokeWidth={st.width} lineDashPattern={l.properties.kind === 'trail' ? [6, 4] : undefined} />
            );
          }
          const [lo, la] = l.geometry.coordinates;
          return (
            <Marker key={l.properties.name} coordinate={{ latitude: la, longitude: lo }} tracksViewChanges={false} anchor={{ x: 0.5, y: 1 }}>
              <View style={s.label}>
                <T v="caption" c={color.ink} style={{ fontSize: 11, fontFamily: font.semibold }}>{`${l.properties.kind === 'peak' ? '▲ ' : ''}${l.properties.name}`}</T>
              </View>
            </Marker>
          );
        })}
        {showSections && sections.map((sec) => (
          <Polygon key={sec.section_id} coordinates={rect(sec.bbox)} strokeColor={color.spruce} strokeWidth={1.5} fillColor="rgba(30,59,50,0.06)" />
        ))}
        {hotspots.map((h) => (
          <Polygon key={h.zone_id} coordinates={rect(h.bbox)} strokeColor={hotspotColor(layer)} strokeWidth={2} fillColor={hotspotColor(layer) + '33'} />
        ))}
        {trees.map((t) => {
          const on = t.id === selected;
          return (
            // Keyed on selection and layer so the custom marker re-renders with tracksViewChanges off.
            <Marker key={`${t.id}${on}${layer}`} coordinate={{ latitude: t.lat!, longitude: t.lng! }} onPress={() => onSelect(t.id)} tracksViewChanges={false}>
              <View style={[s.pin, on && s.pinOn]}>
                <Dot c={pinColor(t, layer)} size={on ? 18 : 12} />
              </View>
            </Marker>
          );
        })}
      </MapView>
      <View style={s.controls}>
        <Pressable style={s.btn} onPress={() => zoom(0.5)} accessibilityLabel="Zoom in"><Icon as={Plus} /></Pressable>
        <Pressable style={s.btn} onPress={() => zoom(2)} accessibilityLabel="Zoom out"><Icon as={Minus} /></Pressable>
        <Pressable style={s.btn} onPress={() => map.current?.animateToRegion(home, 300)} accessibilityLabel="Show all trees"><Icon as={Fit} /></Pressable>
        <Pressable style={[s.btn, satellite && { backgroundColor: color.spruce }]} onPress={() => setSatellite(!satellite)} accessibilityLabel="Satellite view">
          <T v="caption" c={satellite ? color.paper : color.ink} style={{ fontSize: 10, fontFamily: font.semibold }}>SAT</T>
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  pin: { width: 26, height: 26, borderRadius: radius.pill, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  pinOn: { width: 36, height: 36, borderWidth: 2, borderColor: color.ink },
  label: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, backgroundColor: 'rgba(255,255,255,0.85)' },
  controls: { position: 'absolute', right: 16, top: 120, gap: 8 },
  btn: { width: 44, height: 44, borderRadius: radius.sm, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
});
