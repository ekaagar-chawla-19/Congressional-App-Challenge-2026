import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Image, Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import * as api from '@/api';
import { useApp } from '@/device';
import { Camera, ChevronDown, Images, Sparkles, X, Zap } from '@/icons';
import { quickFix } from '@/identify';
import { ModelPicker } from '@/ModelPicker';
import { useModels } from '@/models';
import * as engine from '@/engine';
import { SensorTiles } from '@/SensorPanel';
import { readingForVisit, useConnected, useSensors } from '@/sensors';
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
    const text = p.startsWith('blurry') ? 'Blurry. Hold steady, tap to focus, retake.'
      : p.startsWith('too dark') ? 'Too dark. Find light or use the flash.'
      : p.startsWith('over-exposed') ? 'Too bright. Turn away from the sun.'
      : p.startsWith('no tree') ? 'No bark in view. Aim at the trunk.'
      : p.startsWith('same as view') ? 'Same spot as before. Walk a quarter turn.'
      : `Retake: ${p.split(':')[0]}.`;
    return { text, tone: 'bad' };
  }
  const w = v.warnings.find((x) => x.startsWith('too far') || x.startsWith('almost'));
  const dist = !w ? 'Good photo.' : w.startsWith('too far') ? 'Get closer: fill the frame with bark.' : 'Good. A little closer next time.';
  const h = v.hemlock_probability;
  const sp = h == null ? '' : h >= 0.7 ? ` Hemlock bark ${Math.round(h * 100)}%.`
    : h >= 0.35 ? ` Maybe hemlock (${Math.round(h * 100)}%).` : ` Looks like ${v.top_species?.name ?? 'another species'}.`;
  return { text: dist + sp, tone: w || (h != null && h < 0.7) ? 'warn' : 'good' };
}

export default function Scan() {
  const { mode } = useLocalSearchParams<{ mode?: 'check' }>();
  const check = mode === 'check';
  const CAP = check ? 10 : MAX + 1; // hemlock check: several trees, one photo each; scan: up to 6 trunk views
  const server = isServer();
  const [permission, request, recheck] = useCameraPermissions();
  const open = useRef(true); // a library import stops when the scan is closed
  useEffect(() => () => void (open.current = false), []);
  // Turned on in Settings: pick that up when the user comes back to the app.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (st) => st === 'active' && recheck());
    return () => sub.remove();
  }, [recheck]);
  const unit = useApp((s) => s.unit);
  const connected = useConnected();
  const live = useSensors((st) => st.live);
  const camera = useRef<CameraView>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [msgs, setMsgs] = useState<Msg[]>(() => [{
    id: 0,
    text: check ? 'Photograph the bark of each tree to check.' : 'Fill the frame with bark, 30 to 50 cm away.',
  }]);
  const [torch, setTorch] = useState(false);
  const [busy, setBusy] = useState(false);
  const capture = useRef<{ id: string; next: api.ViewSpec | null } | null>(null);
  const loc = useRef<Promise<api.Location | null> | null>(null);
  const count = useRef({ shots: 0, ok: 0 }); // shots can be added several at a time (library), so not from state
  // Phone-only mode with the on-device model: every photo is checked on the phone, like the server would.
  const onPhone = !server && !check && engine.available();
  const views = useRef<engine.ViewResult[]>([]);
  const say = (text: string, tone?: Msg['tone']) => (setGuide(null), setMsgs((m) => [...m, { id: m.length, text, tone }]));
  // AI-guided scanning: the server's latest read of the evidence (replaces the chat once photos are checked)
  const [guide, setGuide] = useState<api.Guidance | null>(null);
  const [checks, setChecks] = useState<{ uri: string; r: api.SpeciesCheck }[]>([]);

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
      setGuide({ state: 'start', title: 'Photo 1 of 3', detail: 'North side, bark at chest height.', candidates: [], next_view: c.next_view, ready: false, needs_more: false });
    } catch (e) {
      say((e as Error).message, 'warn');
    }
  };

  const ok = shots.filter((s) => s.state === 'ok').length;
  const checking = shots.some((s) => s.state === 'checking');

  const addShot = async (uri: string) => {
    const i = count.current.shots++;
    setShots((s) => [...s, { uri, state: server || onPhone ? 'checking' : 'ok' }]);
    const set = (patch: Partial<Shot>) => setShots((s) => s.map((x, j) => (j === i ? { ...x, ...patch } : x)));
    if (check) {
      say('Checking the species…');
      try {
        const r = server ? await api.speciesCheck(uri) : await engine.speciesCheck(uri);
        set({ state: 'ok', hemlock: r.hemlock_probability, species: r.species.name });
        setChecks((c) => [...c, { uri, r }]);
        const label = r.verdict === 'hemlock' ? 'Eastern hemlock' : r.verdict === 'unsure' ? 'Not sure' : `Not a hemlock: ${r.species.name}`;
        say(`Photo ${i + 1}: ${label} (${Math.round(r.hemlock_probability * 100)}% hemlock).`, r.verdict === 'hemlock' ? 'good' : r.verdict === 'unsure' ? 'warn' : 'bad');
      } catch (e) {
        set({ state: 'rejected' });
        say((e as Error).message.replace('photo rejected before the model: ', "Can't check that photo: "), 'bad');
      }
      return;
    }
    if (onPhone) {
      try {
        const v = await engine.checkPhoto(uri, count.current.ok, views.current.filter((x) => x.accepted));
        views.current.push(v);
        const h = engine.hemlockProbability(v);
        const f = feedback({ index: i, view_type: v.viewKey, accepted: v.accepted, problems: v.problems, warnings: v.warnings,
          metrics: v.metrics, hemlock_probability: h, top_species: null });
        set({ state: v.accepted ? 'ok' : 'rejected', hemlock: h });
        if (!v.accepted) return say(f.text, f.tone);
        const n = ++count.current.ok;
        say(n >= MIN ? `${f.text} Tap Identify.` : `${f.text} ${n} of ${MIN}. Move a quarter turn around the trunk.`, f.tone);
      } catch (e) {
        set({ state: 'rejected' });
        say((e as Error).message, 'bad');
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
      if (r.guidance) return setGuide(r.view.accepted ? r.guidance : { ...r.guidance, detail: f.text });
      if (!r.view.accepted) return say(f.text, f.tone);
      say(r.accepted_views >= MIN ? `${f.text} Tap Identify.` : `${f.text} ${r.accepted_views} of ${MIN}.`, f.tone);
    } catch (e) {
      set({ state: 'rejected' });
      say((e as Error).message, 'bad');
    }
  };

  const shoot = async () => {
    if (busy || shots.length >= CAP + 3 || ok >= CAP) return;
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
      mediaTypes: ['images'], allowsMultipleSelection: true, selectionLimit: CAP - ok, quality: 0.8,
      preferredAssetRepresentationMode: ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
    });
    if (r.canceled) return;
    setBusy(true); // no camera shot in between: each photo's view position comes from the photos before it
    try {
      for (const [k, a] of r.assets.entries()) {
        if (!open.current) return;
        if (r.assets.length > 1 && (server || onPhone || check)) say(`Checking photo ${k + 1} of ${r.assets.length}…`);
        await new Promise((go) => requestAnimationFrame(go)); // let the screen update between photos
        await addShot(a.uri);
      }
    } finally {
      setBusy(false);
    }
  };

  const identify = async () => {
    const good = shots.filter((s) => s.state === 'ok').map((s) => s.uri);
    setBusy(true);
    // With a sensor unit connected, a fresh reading goes with the photos; without one the scan is camera-only.
    if (connected) say('Reading the sensors…');
    const sensors = await readingForVisit();
    if (!server || !capture.current) {
      useApp.getState().setScan({ photos: good, treeId: null, observationId: null, isNew: false, serverResult: null, sensors, fingerprints: null,
        views: onPhone ? views.current.filter((v) => v.accepted) : null });
      return router.replace('/result');
    }
    say(`Comparing with every tree${active ? ` (${active.name})` : ''}…`);
    try {
      const r = await api.identifyCapture(capture.current.id, await (loc.current ?? Promise.resolve(null)), false, sensors?.sensors ?? null);
      if (r.action === 'capture_another_view') {
        capture.current.next = r.next_view;
        setGuide({ state: 'ambiguous', title: 'Need one more view', detail: r.next_view?.title ?? 'Another side of the trunk.', candidates: (r.candidates ?? []).map((c) => ({ tree_id: c.tree_id, probability: c.probability ?? 0, global_score: c.global_score })), next_view: r.next_view, ready: false, needs_more: true });
        return setBusy(false);
      }
      if (r.action === 'retake') {
        say('Retake the photos marked with a red X.', 'bad');
        return setBusy(false);
      }
      useApp.getState().setScan({ photos: good, treeId: null, observationId: null, isNew: false, serverResult: r, sensors, fingerprints: null, views: null });
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
          <Empty icon={Camera} title="Turn on the camera"
            body={permission.canAskAgain ? 'HemlockID takes the bark photos right here in the app and coaches you through each one.'
              : 'Camera access is off for HemlockID. Turn it on in Settings > HemlockID > Camera, then come back. Or use bark photos you already took.'} />
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
        <Button title={permission.canAskAgain ? 'Allow camera' : 'Open Settings'} icon={Camera} onPress={permission.canAskAgain ? request : () => Linking.openSettings()} />
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
        {connected && !check && live && (
          <View style={s.sensors} pointerEvents="none">
            <SensorTiles sensors={live.sensors} dark />
          </View>
        )}
        <View style={s.frame} pointerEvents="none">
          {CORNERS.map((c, i) => <View key={i} style={[s.corner, c]} />)}
        </View>
        {/* Coach: one short card at the bottom of the viewfinder, never a stack */}
        <View style={s.chat} pointerEvents="none">
          {guide && !check ? <GuideCard g={guide} /> : msgs.slice(-1).map((m) => (
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

      {check && checks.length > 0 && (
        <ScrollView style={s.results} contentContainerStyle={{ gap: space.sm }}>
          {checks.map(({ uri, r }, i) => {
            const yes = r.verdict === 'hemlock';
            return (
              <View key={uri} style={s.resultRow} accessibilityLabel={`Photo ${i + 1}: ${r.message}`}>
                <Image source={{ uri }} style={s.resultThumb} />
                <View style={{ flex: 1, gap: 4 }}>
                  <View style={s.between}>
                    <T v="label" c={color.paper}>{yes ? 'Eastern hemlock' : r.verdict === 'unsure' ? 'Not sure' : r.species.name}</T>
                    <T v="label" c={yes ? '#8FB08A' : '#E0B15A'}>{`${Math.round(r.hemlock_probability * 100)}%`}</T>
                  </View>
                  <View style={s.track}><View style={{ width: `${Math.round(r.hemlock_probability * 100)}%`, height: 6, borderRadius: 3, backgroundColor: yes ? '#8FB08A' : '#C9B79C' }} /></View>
                  <T v="caption" c={color.nightText} style={{ fontSize: 13 }}>{`Photo ${i + 1} · hemlock probability`}</T>
                </View>
              </View>
            );
          })}
          <T v="caption" c={color.nightText} style={{ fontSize: 13 }}>{server ? "Uses Model Delta's species check. Model Gamma has none." : "Checked on this phone by Model Delta's species check."}</T>
        </ScrollView>
      )}
      {!check && (
        <View style={s.progress} accessibilityLabel={`${ok} of ${target} photos accepted`}>
          {Array.from({ length: MAX }, (_, i) => <View key={i} style={[s.seg, i < ok && { backgroundColor: i < MIN ? color.paper : color.live }]} />)}
        </View>
      )}
      <View style={s.controls}>
        <View style={{ flex: 1, alignItems: 'flex-start' }}>
          <Pressable style={s.labelled} onPress={library} disabled={busy || ok >= CAP} accessibilityLabel="Choose photos from library">
            <View style={s.round}><Icon as={Images} c={color.paper} /></View>
            <T v="caption" c={color.nightText} style={{ fontSize: 11 }}>Library</T>
          </Pressable>
        </View>
        <Pressable style={s.shutter} onPress={shoot} disabled={busy || ok >= CAP || !permission.granted} accessibilityLabel="Take photo">
          <View style={[s.shutterCore, (busy || ok >= CAP || !permission.granted) && { opacity: 0.4 }]} />
        </Pressable>
        <View style={{ flex: 1, alignItems: 'flex-end' }}>
          {check ? (
            checks.length > 0 && (
              <Pressable style={s.go} onPress={() => router.replace('/scan')}>
                <T v="label" c={color.spruce}>Scan a tree</T>
              </Pressable>
            )
          ) : ok >= MIN ? (
            <Pressable style={[s.go, (busy || checking) && { opacity: 0.5 }]} onPress={identify} disabled={busy || checking}>
              <T v="label" c={color.spruce}>{busy ? 'Checking' : 'Identify'}</T>
            </Pressable>
          ) : (
            <T v="caption" c={color.nightText} style={{ fontSize: 13 }}>{`${MIN - ok} to go`}</T>
          )}
        </View>
      </View>
      {pickerEl}
    </Screen>
  );
}

// AI-guided scanning card: what the evidence says now and what photo would help, in two lines.
function GuideCard({ g }: { g: api.Guidance }) {
  const tone = g.state === 'retake' || g.state === 'contradicting' || g.state === 'species_doubt' ? s.bad
    : g.state === 'ambiguous' || g.needs_more ? s.warn : g.state === 'confident' || g.ready ? s.good : null;
  const bars = ['confident', 'ambiguous', 'building', 'contradicting'].includes(g.state) ? g.candidates.slice(0, 2) : [];
  return (
    <View style={[s.card, tone]} accessibilityLiveRegion="polite" accessibilityLabel={`${g.title}. ${g.detail}`}>
      <View style={s.between}>
        <T v="label" c={color.paper} style={{ fontSize: 16, flex: 1 }} numberOfLines={1}>{g.title}</T>
        <View style={s.ai}>
          <Sparkles size={12} strokeWidth={2} color={color.paper} />
          <T v="caption" c={color.paper} style={{ fontSize: 11, fontFamily: font.semibold }}>AI-guided</T>
        </View>
      </View>
      <T v="caption" c={color.paper} style={{ fontSize: 14, lineHeight: 19 }} numberOfLines={2}>{g.detail}</T>
      {bars.map((c) => (
        <View key={c.tree_id} style={s.candidate}>
          <T v="caption" c={color.paper} style={{ width: 52, fontSize: 13, fontFamily: font.medium }}>{c.tree_id}</T>
          <View style={[s.track, { flex: 1 }]}><View style={{ width: `${Math.max(3, Math.round(c.probability * 100))}%`, height: 6, borderRadius: 3, backgroundColor: color.paper }} /></View>
          <T v="caption" c={color.paper} style={{ width: 40, textAlign: 'right', fontSize: 13 }}>{`${Math.round(c.probability * 100)}%`}</T>
        </View>
      ))}
    </View>
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
  sensors: { position: 'absolute', top: space.md, left: space.md, right: space.md },
  corner: { width: C, height: C },
  chat: { position: 'absolute', left: space.md, right: space.md, bottom: space.md, gap: 6 },
  card: { gap: 6, padding: space.md, borderRadius: 16, backgroundColor: 'rgba(22, 32, 28, 0.88)' },
  ai: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, height: 22, borderRadius: radius.pill, backgroundColor: 'rgba(245, 242, 236, 0.18)' },
  candidate: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  results: { maxHeight: 220, flexGrow: 0 },
  resultRow: { flexDirection: 'row', gap: space.md, alignItems: 'center', padding: space.md, borderRadius: radius.md, backgroundColor: color.nightCard },
  resultThumb: { width: 48, height: 48, borderRadius: 10 },
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
  between: { flexDirection: 'row', justifyContent: 'space-between' },
  track: { height: 6, borderRadius: 3, backgroundColor: color.nightLine },
});
