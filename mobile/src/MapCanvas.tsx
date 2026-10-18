import { StyleSheet, View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';
import type { TreeRow } from './data';
import { color, radius, status } from './theme';
import { Dot } from './ui';

export type MapProps = { trees: TreeRow[]; selected?: string; onSelect(id: string): void };

export default function MapCanvas({ trees, selected, onSelect }: MapProps) {
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
    <MapView style={StyleSheet.absoluteFill} initialRegion={region} showsUserLocation showsMyLocationButton mapType="terrain">
      {trees.map((t) => {
        const on = t.id === selected;
        return (
          // Keyed on selection so the custom marker re-renders with tracksViewChanges off.
          <Marker key={`${t.id}${on}`} coordinate={{ latitude: t.lat!, longitude: t.lng! }} onPress={() => onSelect(t.id)} tracksViewChanges={false}>
            <View style={[s.pin, on && s.pinOn]}>
              <Dot c={status[t.status ?? 'unrated'].dot} size={on ? 20 : 16} />
            </View>
          </Marker>
        );
      })}
    </MapView>
  );
}

const s = StyleSheet.create({
  pin: { width: 36, height: 36, borderRadius: radius.pill, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  pinOn: { width: 44, height: 44, borderWidth: 2, borderColor: color.ink },
});
