import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { Camera, Images, X, Zap } from '@/icons';
import { useRef, useState } from 'react';
import { Image, Pressable, StyleSheet, View } from 'react-native';
import { useApp } from '@/device';
import { color, font, radius, space } from '@/theme';
import { Button, Dot, Empty, Icon, Screen, T } from '@/ui';

const MIN = 3; // the model averages 3 to 5 views of a trunk
const MAX = 5;

export default function Scan() {
  const [permission, request] = useCameraPermissions();
  const unit = useApp((s) => s.unit);
  const camera = useRef<CameraView>(null);
  const [photos, setPhotos] = useState<string[]>([]);
  const [torch, setTorch] = useState(false);
  const [busy, setBusy] = useState(false);

  // Bark photos already on the phone (handy for demos, or when the camera is not available).
  const library = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], allowsMultipleSelection: true, selectionLimit: MAX - photos.length, quality: 0.8 });
    if (!r.canceled) setPhotos((p) => [...p, ...r.assets.map((a) => a.uri)].slice(0, MAX));
  };
  const identify = (shots = photos) => {
    useApp.getState().setScan({ photos: shots, treeId: null, observationId: null, isNew: false });
    router.replace('/result');
  };

  if (!permission) return null;
  if (!permission.granted && photos.length === 0) {
    return (
      <Screen>
        <View style={{ flex: 1, justifyContent: 'center' }}>
          <Empty icon={Camera} title="Camera access needed" body="HemlockID photographs bark to recognise each tree. Photos stay on this phone." />
        </View>
        <Button title="Allow camera" onPress={request} />
        <Button title="Choose bark photos" icon={Images} secondary onPress={library} />
        <Button title="Not now" secondary onPress={() => router.back()} />
      </Screen>
    );
  }

  const shoot = async () => {
    if (busy || photos.length >= MAX) return;
    setBusy(true);
    try {
      const pic = await camera.current?.takePictureAsync({ quality: 0.8 });
      if (pic) setPhotos((p) => [...p, pic.uri]);
    } finally {
      setBusy(false);
    }
  };
  const n = photos.length;

  return (
    <Screen bg={color.ink}>
      <StatusBar style="light" />
      <View style={s.top}>
        <Pressable style={s.round} onPress={() => router.back()} accessibilityLabel="Close scan">
          <Icon as={X} c={color.paper} />
        </Pressable>
        <View style={s.chip}>
          <Dot c={unit ? color.live : color.lichen} />
          <T v="caption" c={color.paper} style={{ fontFamily: font.medium }}>{unit ? `Live from ${unit.name}` : 'Phone camera'}</T>
        </View>
        <Pressable style={[s.round, torch && { backgroundColor: color.paper }]} onPress={() => setTorch(!torch)} accessibilityLabel="Toggle light" accessibilityState={{ selected: torch }}>
          <Icon as={Zap} c={torch ? color.ink : color.paper} />
        </Pressable>
      </View>

      <View style={s.viewport}>
        {permission.granted ? (
          <CameraView ref={camera} style={StyleSheet.absoluteFill} facing="back" enableTorch={torch} />
        ) : n > 0 ? (
          <Image source={{ uri: photos[n - 1] }} style={StyleSheet.absoluteFill} />
        ) : null}
        <View style={s.frame} pointerEvents="none">
          {CORNERS.map((c, i) => <View key={i} style={[s.corner, c]} />)}
        </View>
        <View style={s.tip}>
          <T v="caption" c={color.paper} style={{ fontSize: 14 }}>Fill the frame with bark. Keep 30 to 50 cm away.</T>
        </View>
      </View>

      <View style={{ alignItems: 'center', gap: space.sm }}>
        <T v="label" c={color.paper}>{n >= MAX ? 'All photos taken' : `Photo ${n + 1} of ${MAX}`}</T>
        <T v="caption" c={color.nightText}>{n >= MIN ? 'Ready to identify, or add more views' : 'Move a quarter turn around the trunk each time'}</T>
      </View>
      <View style={s.progress} accessibilityLabel={`${n} of ${MAX} photos taken`}>
        {Array.from({ length: MAX }, (_, i) => <View key={i} style={[s.seg, i < n && { backgroundColor: color.paper }]} />)}
      </View>

      <View style={s.controls}>
        <View style={{ flex: 1, alignItems: 'flex-start' }}>
          <Pressable style={s.round} onPress={library} disabled={n >= MAX} accessibilityLabel="Choose photos from library">
            <Icon as={Images} c={color.paper} />
          </Pressable>
        </View>
        <Pressable style={s.shutter} onPress={shoot} disabled={busy || n >= MAX} accessibilityLabel="Take photo">
          <View style={[s.shutterCore, (busy || n >= MAX) && { opacity: 0.4 }]} />
        </Pressable>
        <View style={{ flex: 1, alignItems: 'flex-end' }}>
          {n >= MIN ? (
            <Pressable style={s.go} onPress={() => identify()}>
              <T v="label" c={color.spruce}>Identify</T>
            </Pressable>
          ) : (
            <T v="caption" c={color.nightText}>{`${MIN - n} to go`}</T>
          )}
        </View>
      </View>
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
  top: { height: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  round: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: color.nightCard, alignItems: 'center', justifyContent: 'center' },
  chip: { flexDirection: 'row', alignItems: 'center', gap: space.sm, height: 36, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: color.nightCard },
  viewport: { flex: 1, borderRadius: 24, overflow: 'hidden', backgroundColor: color.bark, alignItems: 'center', justifyContent: 'center' },
  frame: { width: 240, height: 240 },
  corner: { width: C, height: C },
  tip: { position: 'absolute', left: space.lg, right: space.lg, bottom: space.lg, padding: space.md, borderRadius: 14, backgroundColor: 'rgba(22, 32, 28, 0.82)' },
  progress: { flexDirection: 'row', gap: space.sm },
  seg: { flex: 1, height: 6, borderRadius: radius.pill, backgroundColor: color.nightLine },
  controls: { flexDirection: 'row', alignItems: 'center', height: 80 },
  shutter: { width: 80, height: 80, borderRadius: radius.pill, borderWidth: 3, borderColor: color.paper, alignItems: 'center', justifyContent: 'center' },
  shutterCore: { width: 64, height: 64, borderRadius: radius.pill, backgroundColor: color.paper },
  go: { height: 44, paddingHorizontal: 18, borderRadius: radius.pill, backgroundColor: color.paper, justifyContent: 'center' },
});
