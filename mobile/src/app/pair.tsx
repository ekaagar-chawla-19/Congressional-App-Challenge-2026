import { router } from 'expo-router';
import { Cpu, Wifi } from '@/icons';
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, TextInput, View } from 'react-native';
import { link, useApp, type Unit } from '@/device';
import { NODE, nodeUrl, setNodeUrl } from '@/esp32';
import { color, font, space } from '@/theme';
import { BackBar, Button, Card, IconBox, Row, Screen, T } from '@/ui';

// The unit is an ESP32 with its own Wi-Fi network (firmware/esp32_wifi_node). The phone joins that
// network in Settings, then this screen finds the unit at its address (192.168.4.1).
export default function Pair() {
  const { unit, connecting, connect } = useApp();
  const [found, setFound] = useState<Unit[]>();
  const [error, setError] = useState('');
  const [address, setAddress] = useState(nodeUrl);
  const [editing, setEditing] = useState(false);

  const search = () => {
    setFound(undefined);
    setError('');
    link.discover().then(setFound);
  };
  useEffect(() => void link.discover().then(setFound), []);

  const pick = (id: string) => {
    setError('');
    connect(id).catch((e: Error) => setError(e.message));
  };
  const saveAddress = () => {
    setNodeUrl(address);
    setAddress(nodeUrl());
    setEditing(false);
    search();
  };

  const searching = !found;
  const none = found?.length === 0;
  return (
    <Screen scroll>
      {router.canGoBack() ? <BackBar /> : <View style={{ height: 44 }} />}
      <View style={{ gap: space.sm }}>
        <T v="display">Pair your unit</T>
        <T c={color.inkSoft}>The sensor unit makes its own Wi-Fi network. Your phone joins it to read the sensors.</T>
      </View>

      <Card>
        <Row left={<IconBox icon={Cpu} />} title="1. Turn the unit on" sub="Its network appears a few seconds later." />
        <Row left={<IconBox icon={Wifi} />} title="2. Join its Wi-Fi"
          sub={`In Settings > Wi-Fi, pick HS-ESP32-xxxx. Password: ${NODE.password}. Stay on it if your phone says "No internet".`} />
        <Row left={<IconBox icon={Wifi} />} title="3. Come back here" sub="The unit shows up below." last />
      </Card>

      <Card>
        <Row
          left={<IconBox icon={Wifi} />}
          title={unit ? 'Unit paired' : searching ? 'Looking for the unit' : none ? 'No unit found' : 'Unit found'}
          sub={error || (unit ? 'You can now read its sensors at each tree.' : none ? "Not on the unit's Wi-Fi yet, or it is off. Already on it? Check Settings > HemlockID > Local Network is on." : `At ${address.replace(/^https?:\/\//, '')}`)}
          right={searching ? <ActivityIndicator color={color.spruce} /> : null}
          last={!found?.length}
        />
        {found?.map((u, i) => {
          const on = unit?.id === u.id;
          return (
            <Row
              key={u.id}
              left={<IconBox icon={Cpu} bg={on ? color.spruce : color.lineSoft} fg={on ? color.paper : color.ink} />}
              title={u.name}
              sub={on ? 'Connected' : 'Wi-Fi sensor unit'}
              right={connecting === u.id ? <ActivityIndicator color={color.spruce} /> : <T v="label" c={color.spruce} style={{ fontSize: 13 }}>{on ? 'Paired' : 'Connect'}</T>}
              onPress={on ? undefined : () => pick(u.id)}
              last={i === found.length - 1}
            />
          );
        })}
      </Card>

      {editing ? (
        <View style={{ gap: space.sm }}>
          <T v="caption">{`Unit address. Leave as ${NODE.defaultUrl} for a real unit; use http://<computer-ip>:8090 for \`hemlock-esp32 simulate\`.`}</T>
          <TextInput value={address} onChangeText={setAddress} autoCapitalize="none" autoCorrect={false} keyboardType="url" autoFocus selectTextOnFocus
            returnKeyType="done" onSubmitEditing={saveAddress}
            accessibilityLabel="Unit address" style={s.input} />
          <View style={s.split}>
            <View style={{ flex: 1 }}><Button title="Save" onPress={saveAddress} /></View>
            <View style={{ flex: 1 }}><Button title="Cancel" secondary onPress={() => (setAddress(nodeUrl()), setEditing(false))} /></View>
          </View>
        </View>
      ) : (
        <T v="caption" c={color.spruce} onPress={() => setEditing(true)} style={{ textAlign: 'center', fontFamily: font.medium, padding: space.sm }}>
          {`Unit address: ${address.replace(/^https?:\/\//, '')} · Change`}
        </T>
      )}

      {unit ? (
        <Button title="Continue" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />
      ) : (
        <>
          <Button title={searching ? 'Searching…' : 'Search again'} secondary onPress={search} disabled={searching} />
          <T v="label" c={color.spruce} onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button"
            style={{ textAlign: 'center', padding: space.sm }}>
            {router.canGoBack() ? 'Not now' : 'Skip for now: use the phone camera only'}
          </T>
        </>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  input: { minHeight: 48, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, fontFamily: font.regular, fontSize: 15, color: color.ink },
  split: { flexDirection: 'row', gap: space.md },
});
