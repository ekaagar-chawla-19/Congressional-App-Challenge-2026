import { router, useLocalSearchParams } from 'expo-router';
import { isHemlock, speciesName } from '@/species';
import { MapIcon, Search, TreePine } from '@/icons';
import { useState } from 'react';
import { FlatList, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { ago, listTrees, useQuery } from '@/data';
import { LoadError } from '@/LoadError';
import { color, font, radius, space, type Status } from '@/theme';
import { Badge, Card, Empty, Icon, Row, Screen, T } from '@/ui';

const FILTERS: { label: string; key?: Status }[] = [{ label: 'All' }, { label: 'Healthy', key: 'healthy' }, { label: 'Watch', key: 'watch' }, { label: 'Infested', key: 'infested' }];

export default function Trees() {
  const loaded = useQuery(listTrees);
  const trees = loaded ?? [];
  // The filter lives in the URL so Home's stat tiles can deep-link into it.
  const { filter } = useLocalSearchParams<{ filter?: Status }>();
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const shown = trees.filter((t) => (!filter || t.status === filter) && (!needle || `${t.id} ${t.place} ${speciesName(t.species)}`.toLowerCase().includes(needle)));

  return (
    <Screen tabbed>
      <View style={s.header}>
        <T v="display">Trees</T>
        <Pressable style={s.round} onPress={() => router.navigate('/map')} accessibilityLabel="Show on map">
          <Icon as={MapIcon} />
        </Pressable>
      </View>

      <View style={{ gap: space.lg }}>
        <View style={s.search}>
          <Icon as={Search} c={color.inkSoft} />
          <TextInput value={q} onChangeText={setQ} placeholder="Search by ID or place" placeholderTextColor={color.inkSoft} style={s.input} accessibilityLabel="Search trees" autoCorrect={false} />
        </View>
        <View style={s.filters} accessibilityRole="tablist">
          {FILTERS.map(({ label, key }) => {
            const on = filter === key;
            const n = key ? trees.filter((t) => t.status === key).length : trees.length;
            return (
              <Pressable key={label} onPress={() => router.setParams({ filter: key })} accessibilityState={{ selected: on }} style={[s.chip, on && s.chipOn]}>
                <T v="caption" c={on ? color.paper : color.ink} style={{ fontFamily: font.medium }}>{`${label} ${n}`}</T>
              </Pressable>
            );
          })}
        </View>
      </View>

      <LoadError />
      <Card style={{ flexShrink: 1 }}>
        <FlatList
          data={shown}
          keyExtractor={(t) => t.id}
          renderItem={({ item: t, index }) => (
            <Row title={<T v="id">{t.id}</T>} sub={`${isHemlock(t.species) ? '' : `${speciesName(t.species)} · `}${t.place} · ${ago(t.last_scan)}`} right={t.status && <Badge s={t.status} />} onPress={() => router.push(`/tree/${t.id}`)} last={index === shown.length - 1} />
          )}
          ListEmptyComponent={!loaded ? null : <Empty icon={TreePine} title={trees.length ? 'No matches' : 'No trees yet'} body={trees.length ? 'Try another search or filter.' : 'Trees appear here after your first scan.'} />}
        />
      </Card>
    </Screen>
  );
}

const s = StyleSheet.create({
  header: { height: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  round: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  search: { flexDirection: 'row', alignItems: 'center', gap: space.md, height: 48, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  input: { flex: 1, fontSize: 15, fontFamily: font.regular, color: color.ink },
  filters: { flexDirection: 'row', gap: space.sm },
  chip: { flex: 1, height: 36, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center', backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  chipOn: { backgroundColor: color.spruce, borderColor: color.spruce },
});
