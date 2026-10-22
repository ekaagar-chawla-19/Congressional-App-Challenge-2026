import { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import * as engine from '@/engine';
import { Cpu } from '@/icons';
import { color, space, status } from '@/theme';
import { BackBar, Button, Card, Empty, Row, Screen, T } from '@/ui';

// Runs the on-device model on a known photo and compares it with the server's answer for the same photo, so you
// can see that tree recognition works on this phone without a computer. Also reachable as hemlockid://modelcheck.
export default function ModelCheck() {
  const [res, setRes] = useState<engine.SelfCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (!engine.available()) return;
    let live = true;
    engine.selfCheck().then(
      (r) => { console.log('[modelcheck]', JSON.stringify(r)); if (live) setRes(r); },
      (e: Error) => { console.log('[modelcheck] error', e.message); if (live) setError(e.message); },
    );
    return () => void (live = false);
  }, [run]);

  const again = () => (setRes(null), setError(null), setRun(run + 1));
  return (
    <Screen scroll>
      <BackBar title="On-device model" />
      {!engine.available() ? (
        <Empty icon={Cpu} title="Not in Expo Go" body="The model runs in the HemlockID app build (npx expo run:ios). In Expo Go, trees are picked by hand." />
      ) : error ? (
        <>
          <Empty icon={Cpu} title="Model check failed" body={error} />
          <Button title="Try again" onPress={again} />
        </>
      ) : !res ? (
        <View style={{ alignItems: 'center', gap: space.md, paddingTop: space.xxl }}>
          <ActivityIndicator color={color.spruce} />
          <T v="caption">Running Model Delta on this phone…</T>
        </View>
      ) : (
        <>
          <T v="display">{res.ok ? 'Works on this phone' : 'Does not match the server'}</T>
          <T c={color.inkSoft}>{"Model Delta ran on a test photo here, with no computer. Its fingerprint is compared with the server's for the same photo."}</T>
          <Card>
            <Row title="Same as the server" sub={`fingerprint similarity ${(res.cosine * 100).toFixed(3)}%`} right={<T v="label" c={res.ok ? status.healthy.text : status.infested.text}>{res.ok ? 'Yes' : 'No'}</T>} />
            <Row title="Hemlock probability" sub={`phone ${Math.round((res.hemlock ?? 0) * 1000) / 10}% · server ${Math.round(res.hemlockServer * 1000) / 10}%`} />
            <Row title="Speed" sub={`model load ${res.loadMs} ms · photo decode ${res.decodeMs} ms · model ${res.modelMs} ms`} last />
          </Card>
          <Button title="Run again" secondary onPress={again} />
        </>
      )}
    </Screen>
  );
}
