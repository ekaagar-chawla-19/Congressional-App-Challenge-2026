import { router } from 'expo-router';
import { useDb } from '@/db';
import { useState } from 'react';
import { ChevronRight, LogOut, MapPin, Plus, Trash, Trees } from '@/icons';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';
import { logout } from '@/api';
import { ago, createForest, deleteForest, listForests, useQuery, type Forest } from '@/data';
import { hereNow } from '@/identify';
import { shortName, useSession } from '@/session';
import { color, font, radius, space, status, type Status } from '@/theme';
import { BackBar, Button, Card, ConfirmDelete, Dot, Empty, Icon, IconBox, Screen, T } from '@/ui';

const ORDER: Status[] = ['infested', 'watch', 'healthy', 'unrated'];

export default function Forests() {
  const db = useDb();
  const [rev, setRev] = useState(0); // bumped after a delete to reload the list
  const forests = useQuery(listForests, String(rev));
  const { user, mode, forest: current, setForest } = useSession();
  const [doomed, setDoomed] = useState<Forest | null>(null);
  const remove = async () => {
    await deleteForest(db, doomed!);
    if (current?.id === doomed!.id) setForest(null); // nothing selected until they pick again
    setDoomed(null);
    setRev((r) => r + 1);
  };

  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [here, setHere] = useState(true); // center the new forest where the user stands
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const add = async () => {
    setBusy(true);
    setError('');
    try {
      const f = await createForest(db, name.trim(), here ? await hereNow() : null);
      setAdding(false);
      setName('');
      setForest(f);
      if (router.canGoBack()) router.back();
      else router.replace('/');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const pick = (f: Forest) => {
    setForest({ id: f.id, name: f.name, lat: f.lat, lng: f.lng });
    if (router.canGoBack()) router.back();
    else router.replace('/');
  };
  const signOut = () => {
    if (mode === 'server') logout().catch(() => {});
    useSession.getState().signOut();
    router.replace('/login');
  };

  return (
    <Screen scroll>
      {current && router.canGoBack() ? <BackBar /> : <View style={{ height: space.lg }} />}
      <View style={{ gap: space.sm }}>
        <T v="caption">{`Signed in as ${user?.name ?? ''}${mode === 'local' ? ' · on this phone only' : ''}`}</T>
        <T v="display">Your forests</T>
        <T c={color.inkSoft}>Pick the forest you are working in. You can switch any time from the home screen.</T>
      </View>

      {forests && forests.length === 0 && <Empty icon={Trees} title="No forests yet" body="Add the forest you are surveying to get started." />}

      <View style={{ gap: space.md }}>
        {forests?.map((f) => {
          const on = f.id === current?.id;
          return (
            // The delete button sits beside (not inside) the card's pressable area: no nested buttons.
            <View key={f.id}>
            <Pressable onPress={() => pick(f)} accessibilityRole="button" style={({ pressed }) => [s.card, on && s.cardOn, pressed && { opacity: 0.9 }]}>
              <View style={s.head}>
                <IconBox icon={Trees} bg={on ? color.spruce : color.mossTint} fg={on ? color.paper : color.spruce} />
                <View style={{ flex: 1, gap: 2 }}>
                  <T v="title">{shortName(f.name)}</T>
                  <T v="caption">{`${f.trees} hemlocks · last visit ${ago(f.last_visit).toLowerCase()}`}</T>
                </View>
                <View style={{ width: 36 }} />
                <Icon as={ChevronRight} c={color.lichen} />
              </View>
              {f.trees > 0 && (
                <>
                  <View style={s.bar} accessibilityLabel={ORDER.map((k) => `${f.counts[k]} ${status[k].label}`).join(', ')}>
                    {ORDER.filter((k) => f.counts[k]).map((k) => <View key={k} style={{ flex: f.counts[k], backgroundColor: status[k].dot }} />)}
                  </View>
                  <View style={s.legend}>
                    {ORDER.filter((k) => f.counts[k]).map((k) => (
                      <View key={k} style={s.item}>
                        <Dot c={status[k].dot} />
                        <T v="caption" c={color.ink} style={{ fontFamily: font.medium }}>{`${f.counts[k]} ${status[k].label.toLowerCase()}`}</T>
                      </View>
                    ))}
                  </View>
                </>
              )}
            </Pressable>
            <Pressable onPress={() => setDoomed(f)} hitSlop={8} accessibilityRole="button" accessibilityLabel={`Delete ${shortName(f.name)}`} style={s.trash}>
              <Icon as={Trash} c={color.inkSoft} />
            </Pressable>
            </View>
          );
        })}
      </View>

      {adding ? (
        <Card style={s.add}>
          <T v="title">New forest</T>
          <TextInput value={name} onChangeText={setName} placeholder="e.g. Cook Forest, north ridge" placeholderTextColor={color.lichen}
            autoFocus maxLength={120} returnKeyType="done" onSubmitEditing={() => name.trim() && add()} accessibilityLabel="Forest name" style={s.input} />
          <Pressable onPress={() => setHere(!here)} style={s.here} accessibilityRole="checkbox" accessibilityState={{ checked: here }}>
            <View style={[s.box, here && s.boxOn]}>{here && <Icon as={MapPin} c={color.paper} />}</View>
            <T style={{ flex: 1 }}>Center it where I am now</T>
          </Pressable>
          {error ? <T v="caption" c={status.infested.text}>{error}</T> : null}
          <View style={s.split}>
            <View style={{ flex: 1 }}><Button title={busy ? 'Adding…' : 'Add forest'} onPress={add} disabled={!name.trim() || busy} /></View>
            <View style={{ flex: 1 }}><Button title="Cancel" secondary onPress={() => (setAdding(false), setError(''))} /></View>
          </View>
        </Card>
      ) : (
        <Button title="New forest" icon={Plus} secondary onPress={() => setAdding(true)} />
      )}

      <ConfirmDelete visible={!!doomed} what="forest" name={doomed?.name ?? ''} onCancel={() => setDoomed(null)} onConfirm={remove}
        consequences={`All ${doomed?.trees ?? 0} trees in ${doomed ? shortName(doomed.name) : ''}, with every visit, photo, sensor reading and section, will be completely lost.`} />

      <Pressable onPress={signOut} style={s.signOut} accessibilityRole="button">
        <Icon as={LogOut} c={color.inkSoft} />
        <T v="label" c={color.inkSoft}>Sign out</T>
      </Pressable>
    </Screen>
  );
}

const s = StyleSheet.create({
  card: { gap: space.lg, padding: space.lg, borderRadius: radius.lg, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  cardOn: { borderColor: color.spruce, borderWidth: 2 },
  head: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  bar: { flexDirection: 'row', height: 10, borderRadius: radius.pill, overflow: 'hidden', gap: 2, backgroundColor: color.lineSoft },
  legend: { flexDirection: 'row', flexWrap: 'wrap', columnGap: space.lg, rowGap: space.xs },
  item: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  trash: { position: 'absolute', top: space.lg + 4, right: space.lg + 30, width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  add: { padding: space.lg, gap: space.md },
  input: { minHeight: 52, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.paper, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink },
  here: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 44 },
  box: { width: 28, height: 28, borderRadius: 8, borderWidth: 1.5, borderColor: color.line, alignItems: 'center', justifyContent: 'center', transform: [{ scale: 0.9 }] },
  boxOn: { backgroundColor: color.spruce, borderColor: color.spruce },
  split: { flexDirection: 'row', gap: space.md },
  signOut: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: space.sm, padding: space.md },
});
