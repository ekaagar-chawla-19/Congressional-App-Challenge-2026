import { StyleSheet, View } from 'react-native';
import { useLoadError } from './data';
import { TriangleAlert } from './icons';
import { color, space, status } from './theme';
import { Card, Icon, T } from './ui';

/** Shown on screens whose data could not be loaded (signed in, but the server can't be reached). Nothing otherwise. */
export function LoadError() {
  const error = useLoadError((s) => s.error);
  const retry = useLoadError((s) => s.retry);
  if (!error) return null;
  return (
    <Card style={s.card}>
      <View style={s.head}>
        <Icon as={TriangleAlert} c={status.watch.text} />
        <T v="title" style={{ flex: 1 }}>Could not load</T>
        <T v="label" c={color.spruce} onPress={retry} style={{ padding: space.sm }} accessibilityRole="button">Try again</T>
      </View>
      <T v="caption">{error}</T>
    </Card>
  );
}

const s = StyleSheet.create({
  card: { padding: space.lg, gap: space.sm, backgroundColor: status.watch.tint },
  head: { flexDirection: 'row', alignItems: 'center', gap: space.md },
});
