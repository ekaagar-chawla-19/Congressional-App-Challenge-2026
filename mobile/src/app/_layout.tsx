import { Fraunces_500Medium } from '@expo-google-fonts/fraunces/500Medium';
import { Geist_400Regular } from '@expo-google-fonts/geist/400Regular';
import { Geist_500Medium } from '@expo-google-fonts/geist/500Medium';
import { Geist_600SemiBold } from '@expo-google-fonts/geist/600SemiBold';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import { DbProvider } from '@/db';
import { StatusBar } from 'expo-status-bar';
import { migrate } from '@/data';
import { color } from '@/theme';

export default function RootLayout() {
  const [loaded] = useFonts({ Geist_400Regular, Geist_500Medium, Geist_600SemiBold, Fraunces_500Medium });
  if (!loaded) return null;
  return (
    <DbProvider onInit={migrate}>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: color.paper } }}>
        <Stack.Screen name="scan" options={{ presentation: 'fullScreenModal' }} />
      </Stack>
    </DbProvider>
  );
}
