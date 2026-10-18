import { router } from 'expo-router';
import { Check, ChevronLeft, ChevronRight, Clock, TriangleAlert, type LucideIcon } from './icons';
import type { PropsWithChildren, ReactNode } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, View, type TextProps, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { color, font, radius, space, status, type Status } from './theme';

// One icon size and stroke everywhere.
export const Icon = ({ as: Glyph, c = color.ink }: { as: LucideIcon; c?: string }) => (
  <Glyph size={24} strokeWidth={1.5} color={c} />
);

const type = StyleSheet.create({
  hero: { fontFamily: font.display, fontSize: 48, lineHeight: 54, letterSpacing: -1 },
  display: { fontFamily: font.display, fontSize: 30, lineHeight: 36, letterSpacing: -0.3 },
  id: { fontFamily: font.display, fontSize: 18 },
  title: { fontFamily: font.semibold, fontSize: 17 },
  label: { fontFamily: font.semibold, fontSize: 15 },
  body: { fontFamily: font.regular, fontSize: 15, lineHeight: 22 },
  caption: { fontFamily: font.regular, fontSize: 13, lineHeight: 18 },
  overline: { fontFamily: font.semibold, fontSize: 13, letterSpacing: 0.8, textTransform: 'uppercase' },
});

export const T = ({ v = 'body', c, style, ...p }: TextProps & { v?: keyof typeof type; c?: string }) => (
  <Text style={[type[v], { color: c ?? (v === 'caption' || v === 'overline' ? color.inkSoft : color.ink) }, style]} {...p} />
);

export function Screen({ children, scroll, tabbed, bg = color.paper }: PropsWithChildren<{ scroll?: boolean; tabbed?: boolean; bg?: string }>) {
  const inset = useSafeAreaInsets();
  const pad: ViewStyle = {
    paddingTop: inset.top + space.lg,
    paddingBottom: (tabbed ? 0 : inset.bottom) + space.xl,
    paddingHorizontal: space.xl,
    gap: space.xl,
  };
  return scroll ? (
    <ScrollView style={{ flex: 1, backgroundColor: bg }} contentContainerStyle={pad} keyboardShouldPersistTaps="handled">
      {children}
    </ScrollView>
  ) : (
    <View style={[{ flex: 1, backgroundColor: bg }, pad]}>{children}</View>
  );
}

export const BackBar = ({ title, right }: { title?: string; right?: ReactNode }) => (
  <View style={s.bar}>
    <Pressable onPress={() => router.back()} accessibilityLabel="Back" hitSlop={8} style={s.back}>
      <Icon as={ChevronLeft} />
    </Pressable>
    {title ? <T v="caption">{title}</T> : null}
    <View style={{ minWidth: 44, alignItems: 'flex-end' }}>{right}</View>
  </View>
);

export function Button({ title, onPress, icon, secondary, disabled }: { title: string; onPress: () => void; icon?: LucideIcon; secondary?: boolean; disabled?: boolean }) {
  const fg = secondary ? color.ink : color.paper;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      style={({ pressed }) => [s.button, secondary ? s.secondary : s.primary, { opacity: disabled ? 0.4 : pressed ? 0.85 : 1 }]}>
      {icon ? <Icon as={icon} c={fg} /> : null}
      <T v="label" c={fg} style={secondary && { fontFamily: font.medium }}>{title}</T>
    </Pressable>
  );
}

export const Card = ({ children, style }: PropsWithChildren<{ style?: ViewStyle }>) => <View style={[s.card, style]}>{children}</View>;

export const Dot = ({ c, size = 8 }: { c: string; size?: number }) => (
  <View style={{ width: size, height: size, borderRadius: size, backgroundColor: c }} />
);

export const Badge = ({ s: key }: { s: Status }) => {
  const st = status[key];
  return (
    <View style={[s.badge, { backgroundColor: st.tint }]}>
      <Dot c={st.dot} />
      <T v="caption" c={st.text} style={{ fontFamily: font.semibold }}>{st.label}</T>
    </View>
  );
};

export const IconBox = ({ icon, bg = color.mossTint, fg = color.spruce }: { icon: LucideIcon; bg?: string; fg?: string }) => (
  <View style={[s.iconBox, { backgroundColor: bg }]}>
    <Icon as={icon} c={fg} />
  </View>
);

const STATUS_ICON = { healthy: Check, watch: Clock, infested: TriangleAlert } as const;
export const StatusIcon = ({ s: key }: { s: Status }) => <IconBox icon={STATUS_ICON[key]} bg={status[key].tint} fg={status[key].text} />;

// List row inside a Card. `last` drops the divider.
export function Row({ left, title, sub, right, onPress, last }: { left?: ReactNode; title: ReactNode; sub?: string; right?: ReactNode; onPress?: () => void; last?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={!onPress} style={({ pressed }) => [s.row, !last && s.divider, pressed && { backgroundColor: color.lineSoft }]}>
      {left}
      <View style={{ flex: 1, gap: 2 }}>
        {typeof title === 'string' ? <T v="label">{title}</T> : title}
        {sub ? <T v="caption">{sub}</T> : null}
      </View>
      {right ?? (onPress ? <Icon as={ChevronRight} c={color.lichen} /> : null)}
    </Pressable>
  );
}

export const SectionHead = ({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) => (
  <View style={s.sectionHead}>
    <T v="title" style={{ fontSize: 16 }}>{title}</T>
    {action ? <T v="label" c={color.spruce} onPress={onAction} style={{ fontFamily: font.medium, fontSize: 14 }}>{action}</T> : null}
  </View>
);

export function Segmented<V extends string | number>({ options, value, onChange }: { options: { label: string; value: V }[]; value: V; onChange: (v: V) => void }) {
  return (
    <View style={s.segment}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable key={o.label} onPress={() => onChange(o.value)} accessibilityState={{ selected: on }} style={[s.segItem, on && s.segOn]}>
            <T v="caption" c={on ? color.ink : color.inkSoft} style={{ fontFamily: on ? font.semibold : font.medium }}>{o.label}</T>
          </Pressable>
        );
      })}
    </View>
  );
}

// Bark photo, or a bark-toned block when there is none yet.
export const Photo = ({ uri, height }: { uri?: string; height: number }) =>
  uri ? <Image source={{ uri }} style={[s.photo, { height }]} /> : <View style={[s.photo, { height }]} />;

export const Empty = ({ icon, title, body, children }: PropsWithChildren<{ icon: LucideIcon; title: string; body: string }>) => (
  <View style={s.empty}>
    <IconBox icon={icon} />
    <T v="title">{title}</T>
    <T v="caption" style={{ textAlign: 'center' }}>{body}</T>
    {children}
  </View>
);

const s = StyleSheet.create({
  bar: { height: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  back: { width: 44, height: 44, marginLeft: -10, alignItems: 'center', justifyContent: 'center' },
  button: { height: 56, borderRadius: radius.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: space.sm, paddingHorizontal: space.lg },
  primary: { backgroundColor: color.spruce },
  secondary: { backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  card: { backgroundColor: color.card, borderRadius: radius.md, borderWidth: 1, borderColor: color.line, overflow: 'hidden' },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 28, paddingHorizontal: 10, borderRadius: radius.pill, alignSelf: 'flex-start' },
  iconBox: { width: 44, height: 44, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.lg, minHeight: 72, paddingHorizontal: space.lg, paddingVertical: space.md },
  divider: { borderBottomWidth: 1, borderBottomColor: color.lineSoft },
  sectionHead: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  segment: { flexDirection: 'row', gap: space.xs, padding: space.xs, borderRadius: 14, backgroundColor: color.well },
  segItem: { flex: 1, height: 40, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  segOn: { backgroundColor: color.card, shadowColor: color.ink, shadowOpacity: 0.12, shadowRadius: 2, shadowOffset: { width: 0, height: 1 }, elevation: 1 },
  photo: { alignSelf: 'stretch', borderRadius: radius.md, backgroundColor: color.bark },
  empty: { alignItems: 'center', gap: space.sm, paddingVertical: space.xxl, paddingHorizontal: space.xl },
});
