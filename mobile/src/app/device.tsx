import { router } from 'expo-router';
import Storage from '@/kv';
import { useDb } from '@/db';
import * as Sharing from 'expo-sharing';
import { BatteryMedium, CloudUpload, Cpu, Download, HardDrive, Info, LogOut, RefreshCw, Server, Trees, Wifi, type LucideIcon } from '@/icons';
import { useState } from 'react';
import { Platform, Pressable, StyleSheet, Switch, View } from 'react-native';
import { logout } from '@/api';
import { exportCsv, pendingCount, useQuery } from '@/data';
import { useApp } from '@/device';
import { shortName, useSession } from '@/session';
import { color, radius, space, status } from '@/theme';
import { BackBar, Button, Card, Dot, Empty, Icon, IconBox, Row, Screen, T, notify } from '@/ui';

export default function Device() {
  const db = useDb();
  const unit = useApp((s) => s.unit);
  const pending = useQuery(pendingCount) ?? 0;
  const [sync, setSync] = useState(() => Storage.getItemSync('sync') === 'on');
  const { user, mode, server, forest } = useSession();
  const signOut = () => {
    if (mode === 'server') logout().catch(() => {});
    useSession.getState().signOut();
    router.replace('/login');
  };

  const toggleSync = (on: boolean) => {
    Storage.setItemSync('sync', on ? 'on' : 'off');
    setSync(on);
  };
  const share = async () => {
    try {
      const uri = await exportCsv(db);
      if (Platform.OS === 'web') {
        const [href, name] = uri.split('#');
        return Object.assign(document.createElement('a'), { href, download: name }).click();
      }
      await Sharing.shareAsync(uri, { mimeType: 'text/csv', dialogTitle: 'Export scans' });
    } catch (e) {
      notify('Export failed', String(e));
    }
  };
  const fact = (icon: LucideIcon, label: string, value: string) => (
    <View key={label} style={s.fact}>
      <Icon as={icon} c={color.inkSoft} />
      <View style={{ gap: 2 }}>
        <T v="caption" style={{ fontSize: 12 }}>{label}</T>
        <T v="label">{value}</T>
      </View>
    </View>
  );

  return (
    <Screen scroll>
      <BackBar />
      <T v="display">Device and account</T>

      {unit ? (
        <Card style={{ padding: space.lg, gap: space.lg, borderRadius: radius.lg }}>
          <View style={s.head}>
            <IconBox icon={Cpu} bg={color.spruce} fg={color.paper} />
            <View style={{ flex: 1, gap: space.xs }}>
              <T v="title">{unit.name}</T>
              <View style={s.head}>
                <Dot c={color.moss} />
                <T v="caption" c={status.healthy.text}>Connected</T>
              </View>
            </View>
            <T v="label" c={color.spruce} onPress={() => router.push('/pair')} style={{ paddingVertical: space.md }}>Change</T>
          </View>
          <View style={s.facts}>
            {fact(BatteryMedium, 'Battery', `${unit.battery}%`)}
            {fact(Wifi, 'Signal', unit.signal)}
            {fact(HardDrive, 'Storage', unit.storage)}
            {fact(RefreshCw, 'Firmware', unit.firmware)}
          </View>
        </Card>
      ) : (
        <Card>
          <Empty icon={Cpu} title="No unit paired" body="You can still scan with the phone camera. Pair a unit for field captures.">
            <View style={{ alignSelf: 'stretch', marginTop: space.sm }}>
              <Button title="Pair a unit" onPress={() => router.push('/pair')} />
            </View>
          </Empty>
        </Card>
      )}

      <View style={{ gap: space.md }}>
        <T v="overline">Account</T>
        <Card>
          <Row left={<IconBox icon={mode === 'server' ? Server : Cpu} />} title={user?.name ?? ''} sub={mode === 'server' ? `${user?.email} · ${server.replace(/^https?:\/\//, '')}` : `${user?.email} · offline demo`} />
          <Row left={<IconBox icon={Trees} />} title="Forest" sub={shortName(forest?.name ?? '')} onPress={() => router.push('/forests')} />
          <Row left={<IconBox icon={LogOut} />} title="Sign out" onPress={signOut} last />
        </Card>
      </View>

      <View style={{ gap: space.md }}>
        <T v="overline">Settings</T>
        <Card>
          {mode === 'local' && <Row left={<IconBox icon={CloudUpload} />} title="Sync when online" sub={pending ? `${pending} waiting` : 'All scans synced'} right={<Switch value={sync} onValueChange={toggleSync} trackColor={{ true: color.spruce, false: color.line }} thumbColor={color.card} />} />}
          <Row left={<IconBox icon={Download} />} title="Export data" sub="CSV for forestry teams" onPress={share} />
          <Row left={<IconBox icon={Info} />} title="About HemlockID" sub="How it works and your privacy" onPress={() => router.push('/about')} last />
        </Card>
      </View>
      {unit && (
        <Pressable onPress={useApp.getState().disconnect} style={{ alignSelf: 'center', padding: space.md }}>
          <T v="label" c={color.inkSoft}>Disconnect unit</T>
        </Pressable>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  facts: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  fact: { flexBasis: '48%', flexGrow: 1, flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: radius.sm, backgroundColor: color.paper },
});
