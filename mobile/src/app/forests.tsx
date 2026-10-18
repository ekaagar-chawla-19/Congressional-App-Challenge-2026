import { router } from 'expo-router';
import { ChevronRight, LogOut, Trees } from '@/icons';
import { Pressable, StyleSheet, View } from 'react-native';
import { logout } from '@/api';
import { ago, listForests, useQuery, type Forest } from '@/data';
import { shortName, useSession } from '@/session';
import { color, font, radius, space, status, type Status } from '@/theme';
import { BackBar, Dot, Empty, Icon, IconBox, Screen, T } from '@/ui';

const ORDER: Status[] = ['infested', 'watch', 'healthy', 'unrated'];

export default function Forests() {
  const forests = useQuery(listForests);
  const { user, mode, forest: current, setForest } = useSession();

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
        <T v="caption">{`Signed in as ${user?.name ?? ''}${mode === 'local' ? ' · offline demo' : ''}`}</T>
        <T v="display">Your forests</T>
        <T c={color.inkSoft}>Pick the forest you are working in. You can switch any time from the home screen.</T>
      </View>

      {forests && forests.length === 0 && <Empty icon={Trees} title="No forests yet" body="Forests you create on the server appear here." />}

      <View style={{ gap: space.md }}>
        {forests?.map((f) => {
          const on = f.id === current?.id;
          return (
            <Pressable key={f.id} onPress={() => pick(f)} accessibilityRole="button" style={({ pressed }) => [s.card, on && s.cardOn, pressed && { opacity: 0.9 }]}>
              <View style={s.head}>
                <IconBox icon={Trees} bg={on ? color.spruce : color.mossTint} fg={on ? color.paper : color.spruce} />
                <View style={{ flex: 1, gap: 2 }}>
                  <T v="title">{shortName(f.name)}</T>
                  <T v="caption">{`${f.trees} hemlocks · last visit ${ago(f.last_visit).toLowerCase()}`}</T>
                </View>
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
          );
        })}
      </View>

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
  signOut: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: space.sm, padding: space.md },
});
