import { View } from 'react-native';
import { color, space } from '@/theme';
import { BackBar, Card, Screen, T } from '@/ui';

const SECTIONS = [
  {
    title: 'How identification works',
    body: 'Bark patterns are as individual as fingerprints. HemlockID turns each photo into a compact signature using a vision model trained on bark photos of about a thousand trees, then compares it with the signatures of every tree you have scanned. Several photos from around the trunk are averaged, which makes the match more reliable. If no tree is close enough, the app suggests registering a new one.',
  },
  {
    title: 'Reading the health check',
    body: 'Hemlock woolly adelgid shows up as small white woolly masses where needles meet the twig, on the undersides of branches. Needle loss, a thinning crown and twig dieback follow as an infestation grows. Moderate woolly masses, or any severe sign, mark a tree as infested. Lighter signs mark it for watching.',
  },
  {
    title: 'Your privacy',
    body: 'Trees, photos and health checks are stored on this phone. Nothing leaves it unless you export your data or turn on sync. Location is only used to place trees on your map.',
  },
];

export default function About() {
  return (
    <Screen scroll>
      <BackBar />
      <T v="display">About HemlockID</T>
      {SECTIONS.map(({ title, body }) => (
        <Card key={title} style={{ padding: space.lg, gap: space.sm }}>
          <T v="title">{title}</T>
          <T c={color.inkSoft}>{body}</T>
        </Card>
      ))}
      <View style={{ alignItems: 'center' }}>
        <T v="caption">Built for the Congressional App Challenge</T>
      </View>
    </Screen>
  );
}
