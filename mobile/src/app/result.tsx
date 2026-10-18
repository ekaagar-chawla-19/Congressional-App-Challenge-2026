import { router } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { Camera, Check, Plus, TriangleAlert } from '@/icons';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import * as api from '@/api';
import { fmtDate, listTrees } from '@/data';
import { useApp } from '@/device';
import { identify, MATCH_THRESHOLD, type Identification } from '@/identify';
import { isServer } from '@/session';
import { color, font, radius, space, status } from '@/theme';
import { BackBar, Button, Card, Dot, Empty, Photo, Row, Screen, T, notify } from '@/ui';

const strength = (x: number) => (x >= 0.85 ? 'Very likely' : x >= 0.7 ? 'Likely' : 'Possible');
const pct = (x: number) => `${Math.round(x * 100)}%`;

export default function Result() {
  const db = useSQLiteContext();
  // Taken once: this screen identifies the photos it was opened with, even if a later scan changes them.
  const [photos] = useState(() => useApp.getState().photos);
  const [done] = useState(() => useApp.getState().serverResult); // already identified by the guided capture
  const [res, setRes] = useState<Identification>();
  const [error, setError] = useState<string>();
  const [pick, setPick] = useState(0);
  const [browsing, setBrowsing] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    () => listTrees(db).then((trees) => identify(photos, trees, done)).then(setRes, (e: Error) => setError(e.message)),
    [db, photos, done],
  );
  useEffect(() => void run(), [run]);
  const retry = () => (setError(undefined), run());

  if (error) {
    return (
      <Screen>
        <BackBar title="Scan result" />
        <View style={s.center}>
          <Empty icon={TriangleAlert} title="Could not identify" body={error} />
        </View>
        <Button title="Try again" onPress={retry} />
        <Button title="Back to photos" secondary onPress={() => router.replace('/scan')} />
      </Screen>
    );
  }

  if (!res) {
    return (
      <Screen>
        <View style={s.center}>
          <ActivityIndicator size="large" color={color.spruce} />
          <T v="title">Identifying</T>
          <T v="caption">{isServer() ? 'Checking the species, then comparing bark with every tree in this forest' : 'Comparing bark with your trees'}</T>
        </View>
      </Screen>
    );
  }

  const srv = res.server;
  // Blurry photos, or not a hemlock: nothing to match, ask for new photos.
  if (srv && (srv.status === 'recapture' || srv.status === 'rejected_species' || srv.status === 'unsupported_species')) {
    const notHemlock = srv.status !== 'recapture';
    return (
      <Screen>
        <BackBar title="Scan result" />
        <View style={{ gap: space.sm }}>
          <View style={[s.badge, { backgroundColor: status.watch.tint }]}>
            <Dot c={status.watch.dot} />
            <T v="caption" c={status.watch.text} style={{ fontFamily: font.semibold }}>{notHemlock ? 'Not a hemlock' : 'Photos not clear enough'}</T>
          </View>
          <T v="display">{notHemlock ? "This doesn't look like an Eastern hemlock" : 'Let’s retake those'}</T>
          <T c={color.inkSoft}>
            {notHemlock
              ? `The hemlock model could not confirm Eastern hemlock${srv.species?.hemlock_probability != null ? ` (${pct(srv.species.hemlock_probability)} hemlock)` : ''}. Retake with bark filling the frame, or try another tree.`
              : srv.message}
          </T>
        </View>
        <Photo uri={photos[0]} height={180} />
        {srv.species && <HemlockCheck sp={srv.species} />}
        <View style={{ flex: 1 }} />
        <Button title="Retake photos" icon={Camera} onPress={() => router.replace('/scan')} />
        <Button title="Back home" secondary onPress={() => router.dismissAll()} />
      </Screen>
    );
  }

  // The server's pick goes first, even if the candidate list is ordered differently.
  const matches = [...res.matches];
  if (srv?.status === 'existing' && srv.tree_id) {
    const i = matches.findIndex((m) => m.tree.id === srv.tree_id);
    if (i > 0) matches.unshift(...matches.splice(i, 1));
  }
  const uncertain = srv?.status === 'uncertain';
  const chosen = matches[pick];
  // A hand-picked alternative counts as a match. Otherwise the server decides (an uncertain result is shown
  // as a best guess with its confidence), or offline, the top result must clear the threshold.
  const isMatch = !!chosen && (pick > 0 || (srv ? srv.status === 'existing' || uncertain : chosen.score >= MATCH_THRESHOLD));
  const guess = uncertain && pick === 0;

  const next = async (treeId: string | null) => {
    let id = treeId;
    const oid = srv?.observation_id ?? null;
    if (srv && oid) {
      const already = (srv.status === 'existing' && treeId === srv.tree_id) || (srv.status === 'new' && treeId === null);
      if (already) id = srv.tree_id;
      else {
        setBusy(true);
        try {
          id = (await api.assign(oid, treeId ?? 'new')).tree_id;
        } catch (e) {
          setBusy(false);
          return notify('Could not save', (e as Error).message);
        }
      }
    }
    useApp.getState().setScan({ treeId: id, observationId: oid, isNew: treeId === null });
    router.push('/health');
  };

  const badge = guess
    ? { ...status.watch, label: 'Best guess' }
    : isMatch
      ? { ...status.healthy, label: 'Match found' }
      : { label: 'No close match', tint: color.well, dot: color.inkSoft, text: color.ink };

  return (
    <Screen scroll>
      <BackBar title="Scan result" />

      <View style={{ gap: space.sm }}>
        <View style={[s.badge, { backgroundColor: badge.tint }]}>
          <Dot c={badge.dot} />
          <T v="caption" c={badge.text} style={{ fontFamily: font.semibold }}>{badge.label}</T>
        </View>
        <T v="hero" style={{ fontSize: 56, lineHeight: 60 }}>{isMatch ? chosen.tree.id : 'New tree'}</T>
        <T c={color.inkSoft}>
          {guess
            ? `Not certain. This is the closest tree, ${pct(chosen.score)} confident. Confirm it if it looks right, or register a new tree.`
            : isMatch
              ? `${chosen.tree.place} · registered ${fmtDate(chosen.tree.created_at)}`
              : 'None of your trees looks like this one. Register it to start its history.'}
        </T>

      </View>

      {isMatch && (
        <View style={{ gap: space.sm }}>
          <View style={s.between}>
            <T v="label" style={{ fontSize: 14 }}>Match strength</T>
            <T v="label" c={color.spruce} style={{ fontSize: 14 }}>{`${strength(chosen.score)} · ${pct(chosen.score)}`}</T>
          </View>
          <View style={s.track} accessibilityLabel={`Match strength ${pct(chosen.score)}`}>
            <View style={[s.fill, { width: pct(chosen.score) as `${number}%`, backgroundColor: guess ? status.watch.dot : color.spruce }]} />
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

      {srv?.species && <HemlockCheck sp={srv.species} />}

      {browsing && (
        <Card>
          {matches.map((m, i) => (
            <Row key={m.tree.id} title={<T v="id">{m.tree.id}</T>} sub={`${m.tree.place} · ${pct(m.score)}`} right={i === pick && isMatch ? <T v="caption" c={color.spruce}>Selected</T> : undefined} onPress={() => (setPick(i), setBrowsing(false))} last={i === matches.length - 1} />
          ))}
        </Card>
      )}

      <View style={{ gap: space.md }}>
        {isMatch ? <Button title={`Yes, this is ${chosen.tree.id}`} icon={Check} onPress={() => next(chosen.tree.id)} disabled={busy} /> : <Button title="Register new tree" icon={Plus} onPress={() => next(null)} disabled={busy} />}
        <View style={s.split}>
          {matches.length > 0 && (
            <View style={{ flex: 1 }}>
              <Button title={browsing ? 'Hide matches' : 'Other matches'} secondary onPress={() => setBrowsing(!browsing)} />
            </View>
          )}
          {isMatch && (
            <View style={{ flex: 1 }}>
              <Button title="New tree" icon={Plus} secondary onPress={() => next(null)} disabled={busy} />
            </View>
          )}
        </View>
      </View>
    </Screen>
  );
}

// The species model's verdict: is this an Eastern hemlock, and what else it might be.
function HemlockCheck({ sp }: { sp: api.Species }) {
  const h = sp.hemlock_probability ?? (sp.label === 'tsuga_canadensis' ? sp.confidence : 0);
  const yes = sp.label === 'tsuga_canadensis';
  return (
    <Card style={{ padding: space.lg, gap: space.md }}>
      <View style={s.between}>
        <T v="label">Hemlock check</T>
        <View style={[s.badge, { backgroundColor: yes ? status.healthy.tint : status.watch.tint }]}>
          <Dot c={yes ? status.healthy.dot : status.watch.dot} />
          <T v="caption" c={yes ? status.healthy.text : status.watch.text} style={{ fontFamily: font.semibold }}>{yes ? 'Eastern hemlock' : 'Not confirmed'}</T>
        </View>
      </View>
      {(sp.top.length ? sp.top : [{ label: sp.label, name: sp.name, probability: h }]).map((t) => (
        <View key={t.label} style={{ gap: 4 }}>
          <View style={s.between}>
            <T v="caption" c={color.ink}>{t.name}</T>
            <T v="caption">{pct(t.probability)}</T>
          </View>
          <View style={s.track}>
            <View style={[s.fill, { width: pct(t.probability) as `${number}%`, backgroundColor: t.label === 'tsuga_canadensis' ? color.spruce : color.lichen }]} />
          </View>
        </View>
      ))}
      <T v="caption" style={{ fontSize: 12 }}>From the species model, averaged over your photos. Only Eastern hemlocks get a tree ID.</T>
    </Card>
  );
}

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.md },
  badge: { flexDirection: 'row', alignItems: 'center', gap: space.sm, height: 28, paddingHorizontal: space.md, borderRadius: radius.pill, alignSelf: 'flex-start' },
  between: { flexDirection: 'row', justifyContent: 'space-between' },
  track: { height: 8, borderRadius: radius.pill, backgroundColor: color.line, overflow: 'hidden' },
  fill: { height: 8, borderRadius: radius.pill },
  pair: { flexDirection: 'row', gap: space.md },
  fig: { flex: 1, gap: space.sm },
  split: { flexDirection: 'row', gap: space.md },
});
