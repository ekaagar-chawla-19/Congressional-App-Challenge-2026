import { router } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { Animated, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native';
import { Bark, Fingerprint, MatchPair } from '@/FingerprintArt';
import { ArrowRight, Sparkles, X } from '@/icons';
import { color, font, radius, space } from '@/theme';
import { Icon, Screen, T } from '@/ui';

// "How HemlockID thinks": three short steps, story style. Tap the right side (or Next) to go on, the left side
// to go back; the segmented bar at the bottom fills one cell per step. Illustrations, not real data.

type Step = { kicker: string; title: string; body: string; art: (w: number) => React.ReactNode };

const STEPS: Step[] = [
  {
    kicker: 'Step 1 · Fingerprint',
    title: 'Bark becomes a fingerprint',
    body: 'The model reads each photo in small patches and turns the bark into a list of numbers. Similar bark gives similar numbers.',
    art: (w) => (
      <View style={{ alignItems: 'center', gap: space.lg }}>
        <View style={st.photo}><Bark seed={5} w={w * 0.62} h={w * 0.5} grid /></View>
        <Icon as={ArrowRight} c={color.live} />
        <View style={st.print}><Fingerprint seed={5} w={w * 0.72} h={56} /></View>
        <T v="caption" c={color.nightText} style={{ fontSize: 13 }}>384 numbers per photo (Model Delta)</T>
      </View>
    ),
  },
  {
    kicker: 'Step 2 · Matching',
    title: 'The same ridges line up',
    body: 'A new scan is compared with every tree in the forest. On the same tree, the ridges and marks line up. On another tree, they do not.',
    art: (w) => (
      <View style={{ alignItems: 'center', gap: space.md }}>
        <MatchPair w={w * 0.86} h={w * 0.56} />
        <View style={st.row}>
          <T v="caption" c={color.nightText} style={{ fontSize: 13 }}>Last visit</T>
          <T v="caption" c={color.nightText} style={{ fontSize: 13 }}>Today</T>
        </View>
      </View>
    ),
  },
  {
    kicker: 'Step 3 · Decision',
    title: 'Match, new tree, or one more photo',
    body: 'A match must clear a line set on trees the model never saw. Too close to call? The app asks for another photo instead of guessing.',
    art: (w) => <Decision w={w * 0.86} />,
  },
];

function Decision({ w }: { w: number }) {
  const rows = [
    { id: 'H-017', p: 0.92, tone: color.live },
    { id: 'H-031', p: 0.14, tone: '#C9B79C' },
    { id: 'H-002', p: 0.05, tone: '#C9B79C' },
  ];
  const line = 0.6;
  return (
    <View style={{ width: w, gap: space.md }}>
      {rows.map((r) => (
        <View key={r.id} style={st.bar}>
          <T v="label" c={color.paper} style={{ width: 56 }}>{r.id}</T>
          <View style={st.track}>
            <View style={{ width: `${r.p * 100}%`, height: 10, borderRadius: 5, backgroundColor: r.tone }} />
            <View style={[st.threshold, { left: `${line * 100}%` }]} />
          </View>
          <T v="label" c={color.paper} style={{ width: 44, textAlign: 'right' }}>{`${Math.round(r.p * 100)}%`}</T>
        </View>
      ))}
      <T v="caption" c={color.nightText} style={{ fontSize: 13, marginLeft: 56 + space.sm + (w - 56 - 44 - 2 * space.sm) * line - 30 }}>match line</T>
      <View style={st.outcomes}>
        {[['Match', color.live], ['New tree', '#9EC5E8'], ['One more photo', '#E0B15A']].map(([t, c]) => (
          <View key={t} style={[st.outcome, { borderColor: c }]}><T v="caption" c={c} style={{ fontFamily: font.semibold, fontSize: 13 }}>{t}</T></View>
        ))}
      </View>
    </View>
  );
}

export default function HowItThinks() {
  const { width } = useWindowDimensions();
  const w = Math.min(width, 520) - 2 * space.lg;
  const [i, setI] = useState(0);
  const [fade] = useState(() => new Animated.Value(1));
  const last = i === STEPS.length - 1;
  const go = (d: number) => {
    const n = i + d;
    if (n < 0) return;
    if (n >= STEPS.length) return router.back();
    setI(n);
  };
  useEffect(() => {
    fade.setValue(0);
    Animated.timing(fade, { toValue: 1, duration: 260, useNativeDriver: true }).start();
  }, [i, fade]);
  const step = STEPS[i];

  return (
    <Screen bg={color.ink}>
      <StatusBar style="light" />
      <View style={st.top}>
        <View style={st.badge}>
          <Sparkles size={14} strokeWidth={2} color={color.paper} />
          <T v="caption" c={color.paper} style={{ fontFamily: font.semibold, fontSize: 13 }}>How HemlockID thinks</T>
        </View>
        <Pressable style={st.round} onPress={() => router.back()} accessibilityLabel="Close">
          <Icon as={X} c={color.paper} />
        </Pressable>
      </View>

      <Animated.View style={[st.body, { opacity: fade, transform: [{ translateY: fade.interpolate({ inputRange: [0, 1], outputRange: [12, 0] }) }] }]}>
        <View style={{ gap: space.sm }}>
          <T v="overline" c={color.live}>{step.kicker}</T>
          <T v="display" c={color.paper}>{step.title}</T>
          <T c={color.nightText} style={{ fontSize: 16, lineHeight: 23 }}>{step.body}</T>
        </View>
        <View style={st.art}>{step.art(w)}</View>
        <T v="caption" c={color.lichen} style={{ textAlign: 'center', fontSize: 12 }}>Illustration</T>
        {/* tap zones: left half back, right half next (like a story) */}
        <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
          <View style={st.zones}>
            <Pressable style={{ flex: 1 }} onPress={() => go(-1)} accessibilityLabel="Previous step" />
            <Pressable style={{ flex: 1 }} onPress={() => go(1)} accessibilityLabel="Next step" />
          </View>
        </View>
      </Animated.View>

      <View style={st.foot}>
        <View style={st.segments} accessibilityLabel={`Step ${i + 1} of ${STEPS.length}`}>
          {STEPS.map((_, k) => <View key={k} style={[st.segment, k <= i && st.segmentOn]} />)}
        </View>
        <Pressable style={st.next} onPress={() => go(1)} accessibilityRole="button">
          <T v="label" c={color.spruce}>{last ? 'Done' : 'Next'}</T>
        </Pressable>
      </View>
    </Screen>
  );
}

const st = StyleSheet.create({
  top: { height: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 32, paddingHorizontal: 12, borderRadius: radius.pill, backgroundColor: color.nightCard },
  round: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: color.nightCard, alignItems: 'center', justifyContent: 'center' },
  body: { flex: 1, gap: space.xl, paddingTop: space.lg },
  art: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  photo: { borderRadius: 16, overflow: 'hidden' },
  print: { padding: space.md, borderRadius: 14, backgroundColor: color.nightCard },
  row: { flexDirection: 'row', justifyContent: 'space-around', alignSelf: 'stretch' },
  bar: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  track: { flex: 1, height: 10, borderRadius: 5, backgroundColor: color.nightLine },
  threshold: { position: 'absolute', top: -6, width: 2, height: 22, backgroundColor: color.paper },
  outcomes: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, marginTop: space.sm },
  outcome: { paddingHorizontal: 12, height: 30, borderRadius: radius.pill, borderWidth: 1.5, justifyContent: 'center' },
  zones: { flex: 1, flexDirection: 'row' },
  foot: { gap: space.lg, paddingBottom: space.sm },
  segments: { flexDirection: 'row', gap: space.sm },
  segment: { flex: 1, height: 4, borderRadius: 2, backgroundColor: color.nightLine },
  segmentOn: { backgroundColor: color.paper },
  next: { height: 52, borderRadius: radius.pill, backgroundColor: color.paper, alignItems: 'center', justifyContent: 'center' },
});
