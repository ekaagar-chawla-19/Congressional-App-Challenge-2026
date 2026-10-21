import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import * as api from '@/api';
import { useApp } from '@/device';
import { Camera, Check, ChevronDown, Images, Leaf, X, Zap } from '@/icons';
import { quickFix } from '@/identify';
import { ModelPicker } from '@/ModelPicker';
import { useModels } from '@/models';
import { isServer } from '@/session';
import { color, font, radius, space } from '@/theme';
import { Button, Dot, Empty, Icon, Screen, T } from '@/ui';

const MIN = 3; // the model averages 3 to 5 views of a trunk
const MAX = 5;

type Shot = { uri: string; state: 'checking' | 'ok' | 'rejected'; hemlock?: number | null; species?: string };
type Msg = { id: number; text: string; tone?: 'good' | 'warn' | 'bad' };

// Coaching for one checked photo, in plain words.
function feedback(v: api.ViewQuality): { text: string; tone: Msg['tone'] } {
  if (!v.accepted) {
    // A black or blank frame also fails the blur check; name the real cause first.
    const order = ['too dark', 'over-exposed', 'no tree', 'same as view', 'blurry'];
    const p = [...v.problems].sort((a, b) => (order.findIndex((o) => a.startsWith(o)) + 99) % 99 - (order.findIndex((o) => b.startsWith(o)) + 99) % 99)[0] ?? '';
    const text = p.startsWith('blurry') ? "That one's blurry. Hold the phone steady, tap the bark to focus, and take it again."
      : p.startsWith('too dark') ? 'Too dark to see the bark. Step into better light or turn on the light (top right).'
      : p.startsWith('over-exposed') ? 'Too bright. Turn away from the sun so the bark is evenly lit.'
      : p.startsWith('no tree') ? "I can't see bark in that one. Point the camera at the trunk, 30 to 50 cm away."
      : p.startsWith('same as view') ? "That's the same spot as before. Walk a quarter turn around the trunk first."
      : `Let's retake that one: ${p}.`;
    return { text, tone: 'bad' };
  }
  const w = v.warnings.find((x) => x.startsWith('too far') || x.startsWith('almost'));
  const dist = !w ? 'Perfect distance.' : w.startsWith('too far')
    ? "Okay, you're close. I need you to get this close to the tree bark: fill the whole frame, about 30 cm away."
    : 'Good. Next time a little closer, so the bark fills the frame edge to edge.';
  const h = v.hemlock_probability;
  const sp = h == null ? '' : h >= 0.7 ? ` Looks like hemlock bark (${Math.round(h * 100)}%).`
    : h >= 0.35 ? ` Not sure this is a hemlock yet (${Math.round(h * 100)}%).`
    : ` This looks more like ${v.top_species?.name ?? 'another species'} than hemlock.`;
  return { text: dist + sp, tone: w || (h != null && h < 0.7) ? 'warn' : 'good' };
}

export default function Scan() {
  const { mode } = useLocalSearchParams<{ mode?: 'check' }>();
  const check = mode === 'check';
  const server = isServer();
  const [permission, request] = useCameraPermissions();
  const unit = useApp((s) => s.unit);
  const camera = useRef<CameraView>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [msgs, setMsgs] = useState<Msg[]>(() => [{
    id: 0,
    text: check ? 'Hemlock check: take one close, sharp photo of the bark and I will tell you if it is an Eastern hemlock.'
      : "Let's scan this tree. Stand about 30 to 50 cm from the trunk so the bark fills the frame.",
  }]);
  const [torch, setTorch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<api.SpeciesCheck>();
  const capture = useRef<{ id: string; next: api.ViewSpec | null } | null>(null);
  const loc = useRef<Promise<api.Location | null> | null>(null);
  const count = useRef({ shots: 0, ok: 0 }); // shots can be added several at a time (library), so not from state
  const say = (text: string, tone?: Msg['tone']) => setMsgs((m) => [...m, { id: m.length, text, tone }]);

  // Before the first photo the user picks the model (delta or gamma) that this scan runs on the server.
  const askModel = !check && server;
  const models = useModels();
  const [picker, setPicker] = useState<'first' | 'switch' | null>(askModel ? 'first' : null);
  const [active, setActive] = useState<{ key: api.ModelKey; name: string } | null>(null);

  // List the models and get a location fix in the background while the picker is open.
  useEffect(() => {
    if (!askModel) return;
    loc.current = quickFix();
    useModels.getState().load();
  }, [askModel]);

  // Open a guided capture on the server with the chosen model. Switching models starts the scan again.
  const begin = async (key: api.ModelKey | null) => {
    setPicker(null);
    if (capture.current && active && key === active.key) return;
    if (key) useModels.getState().choose(key);
    if (capture.current) {
      api.cancelCapture(capture.current.id).catch(() => {});
      capture.current = null;
      count.current = { shots: 0, ok: 0 };
      setShots([]);
    }
    try {
      const c = await api.startCapture(key ?? undefined);
      capture.current = { id: c.capture_id, next: c.next_view };
      setActive({ key: c.model, name: c.model_name });
      const m = useModels.getState().list?.find((x) => x.key === c.model);
      const species = !m ? '' : m.checks_species ? ' It checks that each photo is hemlock bark.' : " It doesn't check the species, so make sure this is a hemlock.";
      say(`Using ${c.model_name}.${species} Photo 1: start on the ${c.next_view.key === 'trunk_north' ? 'north' : 'first'} side of the trunk, bark at chest height. I'll check each photo as you go.`);
    } catch (e) {
      say(`${(e as Error).message} Photos will be checked when you tap Identify.`, 'warn');
    }
  };

  const ok = shots.filter((s) => s.state === 'ok').length;
  const checking = shots.some((s) => s.state === 'checking');

  const addShot = async (uri: string) => {
    const i = count.current.shots++;
    setShots((s) => [...s, { uri, state: server ? 'checking' : 'ok' }]);
    const set = (patch: Partial<Shot>) => setShots((s) => s.map((x, j) => (j === i ? { ...x, ...patch } : x)));
    if (check) {
      say('Checking the species…');
      try {
        const r = await api.speciesCheck(uri);
        set({ state: 'ok', hemlock: r.hemlock_probability, species: r.species.name });
        setResult(r);
        say(r.message, r.verdict === 'hemlock' ? 'good' : r.verdict === 'unsure' ? 'warn' : 'bad');
      } catch (e) {
        set({ state: 'rejected' });
        say((e as Error).message.replace('photo rejected before the model: ', "Can't check that photo: "), 'bad');
      }
      return;
    }
    if (!server || !capture.current) {
      const n = ++count.current.ok;
      say(n >= MIN ? `You have ${n} pictures. You're done now: tap Identify, or add more views.` : `Got it, ${n} of ${MIN}. Move a quarter turn around the trunk.`, 'good');
      return;
    }
    try {
      const r = await api.addView(capture.current.id, uri);
      capture.current.next = r.next_view;
      const f = feedback(r.view);
      set({ state: r.view.accepted ? 'ok' : 'rejected', hemlock: r.view.hemlock_probability, species: r.view.top_species?.name });
      if (!r.view.accepted) return say(f.text, f.tone);
      const n = r.accepted_views;
      const next = r.next_view && n < MIN ? ` Next: ${r.next_view.instruction}` : '';
      say(n >= MIN ? `${f.text} You have ${n} pictures. You're done now: tap Identify.` : `${f.text} That's ${n} of ${MIN}.${next}`, f.tone);
    } catch (e) {
      set({ state: 'rejected' });
      say((e as Error).message, 'bad');
    }
  };

  const shoot = async () => {
    if (busy || shots.length >= MAX + 3 || ok >= MAX) return;
    setBusy(true);
    try {
      const pic = await camera.current?.takePictureAsync({ quality: 0.8, imageType: 'jpg' });
      if (pic) await addShot(pic.uri);
    } finally {
      setBusy(false);
    }
  };
  // Bark photos already on the phone (handy for demos, or when the camera is not available).
  const library = async () => {
    // Compatible: iOS hands over a JPEG copy instead of the HEIC original.
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'], allowsMultipleSelection: !check, selectionLimit: check ? 1 : MAX - ok, quality: 0.8,
      preferredAssetRepresentationMode: ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
    });
    if (!r.canceled) for (const a of r.assets) await addShot(a.uri);
  };

  const identify = async () => {
    const good = shots.filter((s) => s.state === 'ok').map((s) => s.uri);
    if (!server || !capture.current) {
      useApp.getState().setScan({ photos: good, treeId: null, observationId: null, isNew: false, serverResult: null });
      return router.replace('/result');
    }
    setBusy(true);
    say(`Comparing this bark with every tree in the forest${active ? ` using ${active.name}` : ''}…`);
    try {
      const r = await api.identifyCapture(capture.current.id, await (loc.current ?? Promise.resolve(null)));
      if (r.action === 'capture_another_view') {
        capture.current.next = r.next_view;
        say(`I'm not sure yet which tree this is. Take one more photo${r.next_view ? `: ${r.next_view.instruction}` : ' from another side.'}`, 'warn');
        return setBusy(false);
      }
      if (r.action === 'retake') {
        say(`${r.message} Retake the photos marked with a red X.`, 'bad');
        return setBusy(false);
      }
      useApp.getState().setScan({ photos: good, treeId: null, observationId: null, isNew: false, serverResult: r });
      router.replace('/result');
    } catch (e) {
      say((e as Error).message, 'bad');
      setBusy(false);
    }
  };

  const pickerEl = (
    <ModelPicker
      visible={picker !== null}
      models={models.list}
      error={models.error}
      value={active?.key ?? models.chosen}
      photos={shots.length}
      first={picker === 'first'}
      onChoose={begin}
      onCancel={() => (picker === 'first' ? router.back() : setPicker(null))}
    />
  );

  if (!permission) return null;
  if (!permission.granted && shots.length === 0) {
    return (
      <Screen>
        <View style={{ flex: 1, justifyContent: 'center' }}>
          <Empty icon={Camera} title="Turn on the camera" body="HemlockID takes the bark photos right here in the app and coaches you through each one." />
        </View>
        {askModel && (
          <Pressable style={s.modelRow} onPress={() => setPicker('switch')} accessibilityRole="button"
            accessibilityLabel={`Model: ${active?.name ?? 'not chosen'}. Change model`}>
            <View style={{ flex: 1, gap: 2 }}>
              <T v="caption">Scanning with</T>
              <T v="label">{active?.name ?? 'No model chosen yet'}</T>
            </View>
            <T v="label" c={color.spruce}>Change</T>
          </Pressable>
        )}
        {askModel && msgs.length > 1 && <T v="caption" c={color.inkSoft}>{msgs[msgs.length - 1].text}</T>}
        <Button title="Allow camera" icon={Camera} onPress={request} />
        <Button title="Use photos from the library" icon={Images} secondary onPress={library} />
        <Button title="Not now" secondary onPress={() => router.back()} />
        {pickerEl}
      </Screen>
    );
  }

  const last = shots[shots.length - 1];
  const target = check ? 1 : MIN;
  return (
    <Screen bg={color.ink}>
      <StatusBar style="light" />
      <View style={s.top}>
        <Pressable style={s.round} onPress={() => router.back()} accessibilityLabel="Close scan">
          <Icon as={X} c={color.paper} />
        </Pressable>
        {askModel ? (
          <Pressable style={s.chip} onPress={() => setPicker('switch')} accessibilityRole="button"
            accessibilityLabel={`Model: ${active?.name ?? 'not chosen'}. Change model`}>
            <Dot c={active ? color.live : color.lichen} />
            <T v="caption" c={color.paper} style={{ fontFamily: font.medium }}>{active?.name ?? 'Choose model'}</T>
            <ChevronDown size={16} strokeWidth={1.75} color={color.paper} />
          </Pressable>
        ) : (
          <View style={s.chip}>
            <Dot c={unit ? color.live : color.lichen} />
            <T v="caption" c={color.paper} style={{ fontFamily: font.medium }}>{check ? 'Hemlock check · Model Delta' : unit ? `Live from ${unit.name}` : 'Bark scan'}</T>
          </View>
        )}
        <Pressable style={[s.round, torch && { backgroundColor: color.paper }]} onPress={() => setTorch(!torch)} accessibilityLabel="Toggle light" accessibilityState={{ selected: torch }}>
          <Icon as={Zap} c={torch ? color.ink : color.paper} />
        </Pressable>
      </View>

      <View style={s.viewport}>
        {permission.granted ? (
          <CameraView ref={camera} style={StyleSheet.absoluteFill} facing="back" enableTorch={torch} />
        ) : last ? (
          <Image source={{ uri: last.uri }} style={StyleSheet.absoluteFill} />
        ) : null}
        <View style={s.frame} pointerEvents="none">
          {CORNERS.map((c, i) => <View key={i} style={[s.corner, c]} />)}
        </View>
        {/* Coach: the latest messages, chat style */}
        <View style={s.chat} pointerEvents="none">
          {msgs.slice(-3).map((m) => (
            <View key={m.id} style={[s.bubble, m.tone === 'good' && s.good, m.tone === 'warn' && s.warn, m.tone === 'bad' && s.bad]}>
              <T v="caption" c={color.paper} style={{ fontSize: 14, lineHeight: 19 }}>{m.text}</T>
            </View>
          ))}
        </View>
      </View>

      {shots.length > 0 && (
        <ScrollView horizontal contentContainerStyle={{ gap: space.sm }} style={{ flexGrow: 0 }}>
          {shots.map((sh, i) => (
            <View key={i} style={[s.thumb, sh.state === 'rejected' && { borderColor: '#D46A55' }]}>
              <Image source={{ uri: sh.uri }} style={StyleSheet.absoluteFill} />
              {sh.state === 'checking' ? <View style={s.thumbCover}><ActivityIndicator color={color.paper} /></View>
                : sh.state === 'rejected' ? <View style={s.thumbCover}><Icon as={X} c={color.paper} /></View>
                : sh.hemlock != null ? (
                  <View style={[s.tag, { backgroundColor: sh.hemlock >= 0.7 ? '#3F5A3C' : sh.hemlock >= 0.35 ? '#7A5414' : '#8A3524' }]}>
                    <T v="caption" c={color.paper} style={{ fontSize: 10, fontFamily: font.semibold }}>{`${Math.round(sh.hemlock * 100)}%`}</T>
                  </View>
                ) : null}
            </View>
          ))}
        </ScrollView>
      )}

      {check && result ? (
        <View style={s.result}>
          <View style={s.inline}>
            <Icon as={result.verdict === 'hemlock' ? Check : Leaf} c={result.verdict === 'hemlock' ? '#8FB08A' : '#E0B15A'} />
            <T v="title" c={color.paper}>{result.verdict === 'hemlock' ? 'Eastern hemlock' : result.verdict === 'unsure' ? 'Not sure' : 'Not a hemlock'}</T>
          </View>
          {result.top.map((t) => (
            <View key={t.label} style={{ gap: 3 }}>
              <View style={s.between}>
                <T v="caption" c={color.nightText}>{t.name}</T>
                <T v="caption" c={color.paper}>{`${Math.round(t.probability * 100)}%`}</T>
              </View>
              <View style={s.track}><View style={{ width: `${Math.round(t.probability * 100)}%`, height: 6, borderRadius: 3, backgroundColor: t.label === 'tsuga_canadensis' ? '#8FB08A' : '#C9B79C' }} /></View>
            </View>
          ))}
          <View style={s.split}>
            <View style={{ flex: 1 }}><Button title="Check another" secondary onPress={() => ((count.current = { shots: 0, ok: 0 }), setShots([]), setResult(undefined), say('Take another photo of the bark.'))} /></View>
            <View style={{ flex: 1 }}><Button title="Scan this tree" onPress={() => router.replace('/scan')} /></View>
          </View>
        </View>
      ) : (
        <>
          <View style={s.progress} accessibilityLabel={`${ok} of ${target} photos accepted`}>
            {Array.from({ length: check ? 1 : MAX }, (_, i) => <View key={i} style={[s.seg, i < ok && { backgroundColor: i < MIN ? color.paper : color.live }]} />)}
          </View>
          <View style={s.controls}>
            <View style={{ flex: 1, alignItems: 'flex-start' }}>
              <Pressable style={s.labelled} onPress={library} disabled={busy || ok >= MAX} accessibilityLabel="Choose photos from library">
                <View style={s.round}><Icon as={Images} c={color.paper} /></View>
                <T v="caption" c={color.nightText} style={{ fontSize: 11 }}>Library</T>
              </Pressable>
            </View>
            <Pressable style={s.shutter} onPress={shoot} disabled={busy || ok >= MAX || !permission.granted} accessibilityLabel="Take photo">
              <View style={[s.shutterCore, (busy || ok >= MAX || !permission.granted) && { opacity: 0.4 }]} />
            </Pressable>
            <View style={{ flex: 1, alignItems: 'flex-end' }}>
              {!check && ok >= MIN ? (
                <Pressable style={[s.go, (busy || checking) && { opacity: 0.5 }]} onPress={identify} disabled={busy || checking}>
                  <T v="label" c={color.spruce}>{busy ? 'Checking' : 'Identify'}</T>
                </Pressable>
              ) : (
                <T v="caption" c={color.nightText}>{check ? '' : `${MIN - ok} to go`}</T>
              )}
            </View>
          </View>
        </>
      )}
      {pickerEl}
    </Screen>
  );
}

const C = 36;
const B = { borderColor: color.paper, position: 'absolute' } as const;
const CORNERS = [
  { ...B, left: 0, top: 0, borderLeftWidth: 3, borderTopWidth: 3, borderTopLeftRadius: 14 },
  { ...B, right: 0, top: 0, borderRightWidth: 3, borderTopWidth: 3, borderTopRightRadius: 14 },
  { ...B, left: 0, bottom: 0, borderLeftWidth: 3, borderBottomWidth: 3, borderBottomLeftRadius: 14 },
  { ...B, right: 0, bottom: 0, borderRightWidth: 3, borderBottomWidth: 3, borderBottomRightRadius: 14 },
];

const s = StyleSheet.create({
  modelRow: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.lg, borderRadius: radius.md, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  top: { height: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  round: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: color.nightCard, alignItems: 'center', justifyContent: 'center' },
  labelled: { alignItems: 'center', gap: 4 },
  chip: { flexDirection: 'row', alignItems: 'center', gap: space.sm, height: 36, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: color.nightCard },
  viewport: { flex: 1, borderRadius: 24, overflow: 'hidden', backgroundColor: color.bark, alignItems: 'center', justifyContent: 'center' },
  frame: { width: 220, height: 220, marginBottom: 90 },
  corner: { width: C, height: C },
  chat: { position: 'absolute', left: space.md, right: space.md, bottom: space.md, gap: 6 },
  bubble: { alignSelf: 'flex-start', maxWidth: '92%', paddingHorizontal: space.md, paddingVertical: 10, borderRadius: 16, borderBottomLeftRadius: 4, backgroundColor: 'rgba(22, 32, 28, 0.86)' },
  good: { backgroundColor: 'rgba(44, 79, 67, 0.94)' },
  warn: { backgroundColor: 'rgba(122, 84, 20, 0.94)' },
  bad: { backgroundColor: 'rgba(138, 53, 36, 0.94)' },
  thumb: { width: 56, height: 56, borderRadius: 12, overflow: 'hidden', borderWidth: 2, borderColor: color.nightLine, backgroundColor: color.bark },
  thumbCover: { ...StyleSheet.absoluteFill, backgroundColor: 'rgba(22,32,28,0.55)', alignItems: 'center', justifyContent: 'center' },
  tag: { position: 'absolute', left: 3, bottom: 3, paddingHorizontal: 4, borderRadius: 5 },
  progress: { flexDirection: 'row', gap: space.sm },
  seg: { flex: 1, height: 6, borderRadius: radius.pill, backgroundColor: color.nightLine },
  controls: { flexDirection: 'row', alignItems: 'center', height: 80 },
  shutter: { width: 80, height: 80, borderRadius: radius.pill, borderWidth: 3, borderColor: color.paper, alignItems: 'center', justifyContent: 'center' },
  shutterCore: { width: 64, height: 64, borderRadius: radius.pill, backgroundColor: color.paper },
  go: { height: 44, paddingHorizontal: 18, borderRadius: radius.pill, backgroundColor: color.paper, justifyContent: 'center' },
  result: { gap: space.md, padding: space.lg, borderRadius: radius.lg, backgroundColor: color.nightCard },
  inline: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  between: { flexDirection: 'row', justifyContent: 'space-between' },
  track: { height: 6, borderRadius: 3, backgroundColor: color.nightLine },
  split: { flexDirection: 'row', gap: space.md },
});
