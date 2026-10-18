import { router } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { Check, Plus } from '@/icons';
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { fmtDate, listTrees } from '@/data';
import { useApp } from '@/device';
import { identify, MATCH_THRESHOLD, type Match } from '@/identify';
import { color, font, radius, space, status } from '@/theme';
import { BackBar, Button, Card, Dot, Photo, Row, Screen, T } from '@/ui';

const strength = (x: number) => (x >= 0.85 ? 'Very likely' : x >= 0.7 ? 'Likely' : 'Possible');

export default function Result() {
  const db = useSQLiteContext();
  const photos = useApp((s) => s.photos);
  const [matches, setMatches] = useState<Match[]>();
  const [pick, setPick] = useState(0);
  const [browsing, setBrowsing] = useState(false);

  useEffect(() => {
    listTrees(db).then((trees) => identify(photos, trees)).then(setMatches);
  }, [db, photos]);

  if (!matches) {
    return (
      <Screen>
        <View style={s.center}>
          <ActivityIndicator size="large" color={color.spruce} />
          <T v="title">Identifying</T>
          <T v="caption">Comparing bark with your trees</T>
        </View>
      </Screen>
    );
  }

  const chosen = matches[pick];
  // A hand-picked alternative counts as a match; the top result must clear the threshold.
  const isMatch = !!chosen && (pick > 0 || chosen.score >= MATCH_THRESHOLD);
  const next = (treeId: string | null) => {
    useApp.getState().setScan({ treeId });
    router.push('/health');
  };
  const pct = (x: number) => `${Math.round(x * 100)}%`;

  return (
    <Screen scroll>
      <BackBar title="Scan result" />

      <View style={{ gap: space.sm }}>
        <View style={[s.badge, { backgroundColor: isMatch ? status.healthy.tint : color.well }]}>
          <Dot c={isMatch ? status.healthy.dot : color.inkSoft} />
          <T v="caption" c={isMatch ? status.healthy.text : color.ink} style={{ fontFamily: font.semibold }}>{isMatch ? 'Match found' : 'No close match'}</T>
        </View>
        <T v="hero" style={{ fontSize: 56, lineHeight: 60 }}>{isMatch ? chosen.tree.id : 'New tree'}</T>
        <T c={color.inkSoft}>{isMatch ? `${chosen.tree.place} · registered ${fmtDate(chosen.tree.created_at)}` : 'None of your trees looks like this one. Register it to start its history.'}</T>
      </View>

      {isMatch && (
        <View style={{ gap: space.sm }}>
          <View style={s.between}>
            <T v="label" style={{ fontSize: 14 }}>Match strength</T>
            <T v="label" c={color.spruce} style={{ fontSize: 14 }}>{`${strength(chosen.score)} · ${pct(chosen.score)}`}</T>
          </View>
          <View style={s.track} accessibilityLabel={`Match strength ${pct(chosen.score)}`}>
            <View style={[s.fill, { width: pct(chosen.score) as `${number}%` }]} />
          </View>
        </View>
      )}

      <View style={s.pair}>
        <View style={s.fig}>
          <Photo uri={photos[0]} height={176} />
          <T v="caption">Today</T>
        </View>
        {isMatch && (
          <View style={s.fig}>
            <Photo uri={chosen.tree.photo ?? undefined} height={176} />
            <T v="caption">Last visit</T>
          </View>
        )}
      </View>

      {browsing && (
        <Card>
          {matches.map((m, i) => (
            <Row key={m.tree.id} title={<T v="id">{m.tree.id}</T>} sub={`${m.tree.place} · ${pct(m.score)}`} right={i === pick && isMatch ? <T v="caption" c={color.spruce}>Selected</T> : undefined} onPress={() => (setPick(i), setBrowsing(false))} last={i === matches.length - 1} />
          ))}
        </Card>
      )}

      <View style={{ gap: space.md }}>
        {isMatch ? <Button title={`Yes, this is ${chosen.tree.id}`} icon={Check} onPress={() => next(chosen.tree.id)} /> : <Button title="Register new tree" icon={Plus} onPress={() => next(null)} />}
        <View style={s.split}>
          {matches.length > 0 && (
            <View style={{ flex: 1 }}>
              <Button title={browsing ? 'Hide matches' : 'Other matches'} secondary onPress={() => setBrowsing(!browsing)} />
            </View>
          )}
          {isMatch && (
            <View style={{ flex: 1 }}>
              <Button title="New tree" icon={Plus} secondary onPress={() => next(null)} />
            </View>
          )}
        </View>
      </View>
    </Screen>
  );
}

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.md },
  badge: { flexDirection: 'row', alignItems: 'center', gap: space.sm, height: 28, paddingHorizontal: space.md, borderRadius: radius.pill, alignSelf: 'flex-start' },
  between: { flexDirection: 'row', justifyContent: 'space-between' },
  track: { height: 8, borderRadius: radius.pill, backgroundColor: color.line, overflow: 'hidden' },
  fill: { height: 8, borderRadius: radius.pill, backgroundColor: color.spruce },
  pair: { flexDirection: 'row', gap: space.md },
  fig: { flex: 1, gap: space.sm },
  split: { flexDirection: 'row', gap: space.md },
});
