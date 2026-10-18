import { router } from 'expo-router';
import Storage from '@/kv';
import { TreePine } from '@/icons';
import { StyleSheet, View } from 'react-native';
import { color, radius, space } from '@/theme';
import { Button, Screen, T } from '@/ui';

export default function Onboarding() {
  const go = (to: '/pair' | '/') => {
    Storage.setItemSync('onboarded', '1');
    router.replace(to);
  };
  return (
    <Screen>
      <View style={s.art} aria-hidden>
        <View style={[s.ring, { width: 264, height: 264 }]}>
          <View style={[s.ring, { width: 200, height: 200, borderColor: color.lineStrong }]}>
            <View style={s.core}>
              <TreePine size={48} strokeWidth={1.25} color={color.paper} />
            </View>
          </View>
        </View>
      </View>
      <View style={{ gap: space.md }}>
        <T v="display" style={{ fontSize: 34, lineHeight: 40 }}>Know every hemlock by its bark.</T>
        <T c={color.inkSoft} style={{ fontSize: 16, lineHeight: 24 }}>
          Scan a tree, and HemlockID tells you which one it is and how its health is changing. No tags or paint needed.
        </T>
      </View>
      <View style={{ gap: space.md }}>
        <Button title="Get started" onPress={() => go('/')} />
        <Button title="Pair a sensor unit first" secondary onPress={() => go('/pair')} />
      </View>
    </Screen>
  );
}

const s = StyleSheet.create({
  art: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  ring: { borderRadius: radius.pill, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  core: { width: 136, height: 136, borderRadius: radius.pill, backgroundColor: color.spruce, alignItems: 'center', justifyContent: 'center' },
});
