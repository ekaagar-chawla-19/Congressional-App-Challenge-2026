import { router } from 'expo-router';
import { ChartColumn, ChevronDown, ChevronRight, CloudUpload, Leaf, ScanLine, TreePine } from '@/icons';
import { Pressable, StyleSheet, View } from 'react-native';
import { ago, dueForRevisit, listTrees, pendingCount, useQuery } from '@/data';
import { useApp } from '@/device';
import { shortName, useSession } from '@/session';
import { color, radius, space, status, type Status } from '@/theme';
import { Card, Dot, Empty, Icon, IconBox, Row, Screen, SectionHead, StatusIcon, T } from '@/ui';

const today = () => new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });

export default function Home() {
  const trees = useQuery(listTrees) ?? [];
  const pending = useQuery(pendingCount) ?? 0;
  const unit = useApp((s) => s.unit);
  const forest = useSession((s) => s.forest);
  const user = useSession((s) => s.user);
  const initials = (user?.name ?? '?').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  const due = dueForRevisit(trees).slice(0, 2);
  const open = (id: string) => router.push(`/tree/${id}`);
  const stat = (label: string, n: number, key?: Status) => (
    <Pressable key={label} style={s.stat} onPress={() => router.navigate(key ? `/trees?filter=${key}` : '/trees')}>
      <T v="display" c={key ? status[key].text : color.ink}>{n}</T>
      <View style={s.inline}>
        {key ? <Dot c={status[key].dot} /> : null}
        <T v="caption">{label}</T>
      </View>
    </Pressable>
  );

  return (
    <Screen scroll tabbed>
      <View style={s.header}>
        <Pressable style={{ gap: 2, flex: 1 }} onPress={() => router.push('/forests')} accessibilityRole="button" accessibilityLabel="Switch forest">
          <T v="caption">{today()}</T>
          <View style={s.inline}>
            <T v="display" style={{ fontSize: 24, lineHeight: 30, flexShrink: 1 }} numberOfLines={2}>{shortName(forest?.name ?? 'HemlockID')}</T>
            <Icon as={ChevronDown} c={color.inkSoft} />
          </View>
        </Pressable>
        {/* Account, sensor unit and settings; the dot shows whether a unit is connected. */}
        <Pressable style={s.avatar} onPress={() => router.push('/device')} accessibilityRole="button"
          accessibilityLabel={`Account and settings${unit ? `, unit connected, battery ${unit.battery} percent` : ''}`}>
          <T v="label" c={color.paper} style={{ fontSize: 15 }}>{initials}</T>
          <View style={[s.unitDot, { backgroundColor: unit ? color.live : color.lichen }]} />
        </Pressable>
      </View>

      <Pressable style={s.hero} onPress={() => router.push('/scan')} accessibilityRole="button">
        <IconBox icon={ScanLine} bg={color.spruceSoft} fg={color.paper} />
        <View style={{ flex: 1, gap: space.xs }}>
          <T v="title" c={color.paper} style={{ fontSize: 19 }}>Scan a tree</T>
          <T v="caption" c={color.lineSoft}>{unit ? 'Unit is ready. About 1 minute.' : 'Using the phone camera.'}</T>
        </View>
        <Icon as={ChevronRight} c={color.paper} />
      </Pressable>

      <View style={s.quick}>
        <Pressable style={s.quickBtn} onPress={() => router.push('/scan?mode=check')} accessibilityRole="button">
          <IconBox icon={Leaf} />
          <View style={{ flex: 1 }}>
            <T v="label" style={{ fontSize: 14 }}>Hemlock check</T>
            <T v="caption" style={{ fontSize: 12 }}>Is this tree a hemlock?</T>
          </View>
        </Pressable>
        <Pressable style={s.quickBtn} onPress={() => router.navigate('/insights')} accessibilityRole="button">
          <IconBox icon={ChartColumn} />
          <View style={{ flex: 1 }}>
            <T v="label" style={{ fontSize: 14 }}>Insights</T>
            <T v="caption" style={{ fontSize: 12 }}>Diseases and trends</T>
          </View>
        </Pressable>
      </View>

      <View style={s.stats}>
        {stat('Tracked', trees.length)}
        {stat('Watch', trees.filter((t) => t.status === 'watch').length, 'watch')}
        {stat('Infested', trees.filter((t) => t.status === 'infested').length, 'infested')}
      </View>

      {trees.length === 0 ? (
        <Empty icon={TreePine} title="No trees yet" body="Scan your first hemlock to start tracking its health." />
      ) : (
        <>
          {due.length > 0 && (
            <View style={{ gap: space.md }}>
              <SectionHead title="Due for a revisit" action="See all" onAction={() => router.navigate('/trees')} />
              <Card>
                {due.map((t, i) => (
                  <Row key={t.id} left={<StatusIcon s={t.status!} />} title={t.id} sub={`${status[t.status!].label} · last scan ${ago(t.last_scan).toLowerCase()}`} onPress={() => open(t.id)} last={i === due.length - 1} />
                ))}
              </Card>
            </View>
          )}
          <View style={{ gap: space.md }}>
            <SectionHead title="Recent scans" />
            <Card>
              {trees.slice(0, 2).map((t, i, shown) => (
                <Row key={t.id} left={<StatusIcon s={t.status!} />} title={t.id} sub={`${status[t.status!].label} · ${ago(t.last_scan)}`} onPress={() => open(t.id)} last={i === shown.length - 1 && !pending} />
              ))}
              {pending > 0 && (
                <Row last left={<IconBox icon={CloudUpload} bg={color.lineSoft} fg={color.inkSoft} />} title={`${pending} ${pending === 1 ? 'scan' : 'scans'} waiting to sync`} sub="Saved on this phone. Syncs when online." />
              )}
            </Card>
          </View>
        </>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: color.spruce, alignItems: 'center', justifyContent: 'center' },
  unitDot: { position: 'absolute', right: 0, bottom: 0, width: 12, height: 12, borderRadius: 6, borderWidth: 2, borderColor: color.paper },
  header: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.md },
  hero: { flexDirection: 'row', alignItems: 'center', gap: space.lg, padding: space.xl, borderRadius: radius.lg, backgroundColor: color.spruce },
  stats: { flexDirection: 'row', gap: space.md },
  quick: { flexDirection: 'row', gap: space.md },
  quickBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: radius.md, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  stat: { flex: 1, gap: space.sm, padding: space.lg, borderRadius: radius.md, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  inline: { flexDirection: 'row', alignItems: 'center', gap: 6 },
});
