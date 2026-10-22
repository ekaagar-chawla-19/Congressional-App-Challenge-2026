import { router } from 'expo-router';
import { localDbAvailable, useDb } from '@/db';
import Storage from '@/kv';
import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { defaultServer, hasDefaultServer, login, type ApiError } from '@/api';
import { seedDemo } from '@/data';
import * as engine from '@/engine';
import { Eye, EyeOff, Lock, Mail, Server, TreePine, type LucideIcon } from '@/icons';
import { useSession } from '@/session';
import { color, font, radius, space } from '@/theme';
import { Button, Icon, Screen, T } from '@/ui';

const DEMO = { email: 'demo@hemlock.test', password: 'hemlock-demo' };

export default function Login() {
  const db = useDb();
  const signIn = useSession((s) => s.signIn);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [server, setServer] = useState(() => Storage.getItemSync('server') || defaultServer());
  // A fresh install of the app build has no server address to guess: ask for it.
  const [editServer, setEditServer] = useState(() => !Storage.getItemSync('server') && !hasDefaultServer());
  const [starting, setStarting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ msg: string; offline?: boolean }>();

  const submit = async () => {
    setError(undefined);
    if (!email.trim() || !password) return setError({ msg: 'Enter your email and password.' });
    setBusy(true);
    const url = server.trim().replace(/\/$/, '');
    try {
      const r = await login(url, email.trim(), password);
      Storage.setItemSync('server', url);
      signIn({ mode: 'server', server: url, token: r.token, user: { name: r.user.name, email: r.user.email } });
      router.replace('/forests');
    } catch (e) {
      const err = e as ApiError;
      setError({ msg: err.code === 'bad_credentials' ? 'Wrong email or password.' : err.message, offline: err.code === 'offline' });
      setBusy(false);
    }
  };

  const phoneOnly = async () => {
    if (starting) return;
    setStarting(true);
    setError(undefined);
    try {
      await seedDemo(db);
      signIn({ mode: 'local', server: '', token: null, user: { name: 'Field Team', email: 'on this phone' } });
      router.replace('/forests');
    } catch (e) {
      setError({ msg: `Could not set up phone-only mode: ${(e as Error).message}` });
      setStarting(false);
    }
  };

  const field = (icon: LucideIcon, props: React.ComponentProps<typeof TextInput>, right?: React.ReactNode) => (
    <View style={s.field}>
      <Icon as={icon} c={color.inkSoft} />
      <TextInput placeholderTextColor={color.inkSoft} style={s.input} autoCapitalize="none" autoCorrect={false} {...props} />
      {right}
    </View>
  );

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen scroll>
        <View style={s.brand}>
          <View style={s.mark}>
            <TreePine size={32} strokeWidth={1.5} color={color.paper} />
          </View>
          <T v="overline" c={color.spruce}>HemlockID</T>
        </View>

        <View style={{ gap: space.sm }}>
          <T v="display">Welcome back</T>
          <T c={color.inkSoft}>Sign in to see your forests and the hemlocks you are tracking.</T>
        </View>

        <View style={{ gap: space.md }}>
          {field(Mail, { value: email, onChangeText: setEmail, placeholder: 'Email', keyboardType: 'email-address', textContentType: 'username', accessibilityLabel: 'Email' })}
          {field(Lock, { value: password, onChangeText: setPassword, placeholder: 'Password', secureTextEntry: !show, textContentType: 'password', onSubmitEditing: submit, accessibilityLabel: 'Password' },
            <Pressable onPress={() => setShow(!show)} hitSlop={8} accessibilityLabel={show ? 'Hide password' : 'Show password'}>
              <Icon as={show ? EyeOff : Eye} c={color.inkSoft} />
            </Pressable>)}
          {error && <T v="caption" c={color.bark} style={s.error}>{error.msg}</T>}
          <Button title={busy ? 'Signing in' : 'Sign in'} onPress={submit} disabled={busy} />
          {busy && <ActivityIndicator color={color.spruce} />}
        </View>

        <Pressable style={s.demo} onPress={() => (setEmail(DEMO.email), setPassword(DEMO.password), setError(undefined))} accessibilityRole="button">
          <T v="label" style={{ fontSize: 14 }}>Trying it out?</T>
          <T v="caption">Tap to fill in the demo account: {DEMO.email} / {DEMO.password}</T>
        </Pressable>

        <View style={{ gap: space.md }}>
          <View style={s.or}>
            <View style={s.rule} />
            <T v="caption">or</T>
            <View style={s.rule} />
          </View>
          <Button title={starting ? 'Setting up…' : 'Use on this phone only'} secondary onPress={phoneOnly} disabled={!localDbAvailable || starting} />
          <T v="caption" style={{ textAlign: 'center' }}>
            {!localDbAvailable ? 'Phone-only mode needs the app (Expo Go) or this page opened as localhost. Here, sign in with the demo account above.'
              : error?.offline ? 'No server to sign in to? Phone-only mode keeps everything on this phone, with sample forests to start.'
              : `Everything stays on this phone, with sample forests to start. No computer needed${engine.available() ? ': trees are identified on the phone' : ''}.`}
          </T>
        </View>

        <View style={{ gap: space.sm }}>
          <Pressable style={s.server} onPress={() => setEditServer(!editServer)} accessibilityRole="button">
            <Icon as={Server} c={color.inkSoft} />
            <T v="caption" style={{ flex: 1 }} numberOfLines={1}>Server  {server}</T>
            <T v="caption" c={color.spruce} style={{ fontFamily: font.semibold }}>{editServer ? 'Done' : 'Change'}</T>
          </Pressable>
          {editServer && field(Server, { value: server, onChangeText: setServer, placeholder: 'http://192.168.1.20:8000', keyboardType: 'url', accessibilityLabel: 'Server address' })}
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  brand: { alignItems: 'center', gap: space.md, paddingTop: space.xl },
  mark: { width: 72, height: 72, borderRadius: radius.lg, backgroundColor: color.spruce, alignItems: 'center', justifyContent: 'center' },
  field: { flexDirection: 'row', alignItems: 'center', gap: space.md, height: 56, paddingHorizontal: space.lg, borderRadius: 14, backgroundColor: color.card, borderWidth: 1, borderColor: color.line },
  input: { flex: 1, height: '100%', fontSize: 16, fontFamily: font.regular, color: color.ink },
  error: { fontFamily: font.medium, color: '#8A3524' },
  demo: { gap: 2, padding: space.lg, borderRadius: radius.md, backgroundColor: color.mossTint },
  or: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  rule: { flex: 1, height: 1, backgroundColor: color.line },
  server: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.sm },
});
