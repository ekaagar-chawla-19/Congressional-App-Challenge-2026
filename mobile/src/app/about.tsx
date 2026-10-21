import { router } from 'expo-router';
import { View } from 'react-native';
import { ChevronRight, Sparkles } from '@/icons';
import { color, space } from '@/theme';
import { BackBar, Card, Clamp, IconBox, Row, Screen, T } from '@/ui';

const SECTIONS = [
  {
    title: 'How identification works',
    body: 'Bark is as individual as a fingerprint. The model turns each photo into numbers and compares them with every tree you have scanned. No close match means a new tree.',
  },
  {
    title: 'Reading the health check',
    body: 'Woolly adelgid shows as small white woolly masses where needles meet the twig, under the branches. Needle loss, a thinning crown and dieback follow. Moderate wool or any severe sign marks a tree infested.',
  },
  {
    title: 'Your privacy',
    body: 'Signed in, trees and photos are stored on your HemlockID server. Location only places trees on your map.',
  },
];

export default function About() {
  return (
    <Screen scroll>
      <BackBar />
      <T v="display">About HemlockID</T>
      <Card>
        <Row left={<IconBox icon={Sparkles} />} title="How HemlockID thinks" sub="Fingerprints and matching, in 3 steps" right={<ChevronRight size={20} color={color.lichen} />} onPress={() => router.push('/fingerprint')} last />
      </Card>
      {SECTIONS.map(({ title, body }) => (
        <Card key={title} style={{ padding: space.lg, gap: space.sm }}>
          <T v="title">{title}</T>
          <Clamp>{body}</Clamp>
        </Card>
      ))}
      <View style={{ alignItems: 'center' }}>
        <T v="caption">Built for the Congressional App Challenge</T>
      </View>
    </Screen>
  );
}
