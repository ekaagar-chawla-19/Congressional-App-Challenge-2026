import { router } from 'expo-router';
import { Cpu, Wifi } from '@/icons';
import { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { link, useApp, type Unit } from '@/device';
import { color, space } from '@/theme';
import { BackBar, Button, Card, IconBox, Row, Screen, T } from '@/ui';

export default function Pair() {
  const { unit, connecting, connect } = useApp();
  const [found, setFound] = useState<Unit[]>();
  const [error, setError] = useState('');
  useEffect(() => void link.discover().then(setFound), []);

  const pick = (id: string) => {
    setError('');
    connect(id).catch((e: Error) => setError(e.message));
  };

  return (
    <Screen>
      {router.canGoBack() ? <BackBar /> : <View style={{ height: 44 }} />}
      <View style={{ gap: space.sm }}>
        <T v="display">Pair your unit</T>
        <T c={color.inkSoft}>Turn the unit on and hold it near your phone. Pick it from the list below.</T>
      </View>

      <Card>
        <Row
          left={<IconBox icon={Wifi} />}
          title={unit ? 'Unit paired' : found ? `${found.length} units nearby` : 'Searching for units'}
          sub={error || (unit ? 'You can now scan trees with it.' : 'Keep the unit within 2 metres.')}
          right={found ? null : <ActivityIndicator color={color.spruce} />}
          last
        />
      </Card>

      {found && (
        <Card>
          {found.map((u, i) => {
            const on = unit?.id === u.id;
            return (
              <Row
                key={u.id}
                left={<IconBox icon={Cpu} bg={on ? color.spruce : color.lineSoft} fg={on ? color.paper : color.ink} />}
                title={u.name}
                sub={on ? 'Connected' : `${u.signal} signal`}
                right={connecting === u.id ? <ActivityIndicator color={color.spruce} /> : <T v="label" c={color.spruce} style={{ fontSize: 13 }}>{on ? 'Paired' : 'Connect'}</T>}
                onPress={on ? undefined : () => pick(u.id)}
                last={i === found.length - 1}
              />
            );
          })}
        </Card>
      )}

      <View style={{ flex: 1 }} />
      {unit ? (
        <Button title="Continue" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />
      ) : (
        <T v="caption" style={{ textAlign: 'center' }}>Unit not showing? Hold its power button for 3 seconds until the light blinks.</T>
      )}
    </Screen>
  );
}
