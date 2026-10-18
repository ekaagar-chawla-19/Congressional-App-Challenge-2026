import { Redirect, router, Tabs } from 'expo-router';
import Storage from 'expo-sqlite/kv-store';
import { Cpu, House, MapIcon, ScanLine, TreePine, type LucideIcon } from '@/icons';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { color, font, radius, space } from '@/theme';
import { Icon } from '@/ui';

const TABS: Record<string, [string, LucideIcon]> = {
  index: ['Home', House],
  trees: ['Trees', TreePine],
  map: ['Map', MapIcon],
  device: ['Device', Cpu],
};

export default function TabsLayout() {
  if (!Storage.getItemSync('onboarded')) return <Redirect href="/onboarding" />;
  return (
    <Tabs screenOptions={{ headerShown: false }} tabBar={(p) => <TabBar {...p} />}>
      {Object.keys(TABS).map((name) => <Tabs.Screen key={name} name={name} />)}
    </Tabs>
  );
}

type BarProps = Parameters<NonNullable<ComponentProps<typeof Tabs>['tabBar']>>[0];

// Five equal slots; Scan sits in the middle and opens the scan flow instead of a tab.
function TabBar({ state, navigateToTab, insets }: BarProps) {
  const slot = (label: string, icon: LucideIcon, on: boolean, onPress: () => void, filled = false) => (
    <Pressable key={label} onPress={onPress} accessibilityRole="tab" accessibilityState={{ selected: on }} style={s.slot}>
      <View style={[s.pill, on && { backgroundColor: color.mossTint }, filled && { backgroundColor: color.spruce }]}>
        <Icon as={icon} c={filled ? color.paper : on ? color.spruce : color.inkSoft} />
      </View>
      <Text style={[s.label, on || filled ? s.labelOn : null]}>{label}</Text>
    </Pressable>
  );
  const items = state.routes.map((r, i) => slot(...TABS[r.name], state.index === i, () => navigateToTab(r.key)));
  items.splice(2, 0, slot('Scan', ScanLine, false, () => router.push('/scan'), true));
  return <View style={[s.bar, { paddingBottom: Math.max(insets.bottom, space.sm) }]}>{items}</View>;
}

const s = StyleSheet.create({
  bar: { flexDirection: 'row', paddingTop: space.sm, paddingHorizontal: space.sm, backgroundColor: color.card, borderTopWidth: 1, borderTopColor: color.line },
  slot: { flex: 1, alignItems: 'center', gap: space.xs, minHeight: 56 },
  pill: { width: 56, height: 32, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
  label: { fontSize: 11, fontFamily: font.medium, color: color.inkSoft },
  labelOn: { fontFamily: font.semibold, color: color.spruce },
});
