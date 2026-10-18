import { router } from 'expo-router';
import Storage from 'expo-sqlite/kv-store';
import { useSQLiteContext } from 'expo-sqlite';
import * as Sharing from 'expo-sharing';
import { BatteryMedium, CloudUpload, Cpu, Download, HardDrive, Info, RefreshCw, Wifi, type LucideIcon } from '@/icons';
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, Switch, View } from 'react-native';
import { exportCsv, pendingCount, useQuery } from '@/data';
import { useApp } from '@/device';
import { color, radius, space, status } from '@/theme';
import { Button, Card, Dot, Empty, Icon, IconBox, Row, Screen, T } from '@/ui';

export default function Device() {
  const db = useSQLiteContext();
  const unit = useApp((s) => s.unit);
  const pending = useQuery(pendingCount) ?? 0;
  const [sync, setSync] = useState(() => Storage.getItemSync('sync') === 'on');

  const toggleSync = (on: boolean) => {
    Storage.setItemSync('sync', on ? 'on' : 'off');
    setSync(on);
  };
  const share = async () => {
    try {
      await Sharing.shareAsync(await exportCsv(db), { mimeType: 'text/csv', dialogTitle: 'Export scans' });
    } catch (e) {
      Alert.alert('Export failed', String(e));
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
    <Screen scroll tabbed>
      <View style={{ height: 44, justifyContent: 'center' }}>
        <T v="display">Device</T>
      </View>

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
        <T v="overline">Settings</T>
        <Card>
          <Row left={<IconBox icon={CloudUpload} />} title="Sync when online" sub={pending ? `${pending} waiting` : 'All scans synced'} right={<Switch value={sync} onValueChange={toggleSync} trackColor={{ true: color.spruce, false: color.line }} thumbColor={color.card} />} />
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
