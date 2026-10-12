// Each weight from its own path: the package index would bundle all nine.
import { Onest_400Regular } from "@expo-google-fonts/onest/400Regular";
import { Onest_500Medium } from "@expo-google-fonts/onest/500Medium";
import { Onest_600SemiBold } from "@expo-google-fonts/onest/600SemiBold";
import { Onest_700Bold } from "@expo-google-fonts/onest/700Bold";
import { Onest_800ExtraBold } from "@expo-google-fonts/onest/800ExtraBold";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AppProvider, useApp } from "../state/app";
import { ThemeProvider } from "../ui/theme";

void SplashScreen.preventAutoHideAsync();

function Gate() {
  const { boot } = useApp();
  const signedIn = boot === "signed-in";
  return (
    <Stack screenOptions={{ headerShown: false, animation: "fade" }}>
      <Stack.Protected guard={signedIn}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="capture" options={{ animation: "slide_from_right" }} />
        <Stack.Screen name="done" options={{ gestureEnabled: false }} />
      </Stack.Protected>
      <Stack.Protected guard={!signedIn}>
        <Stack.Screen name="welcome" />
        <Stack.Screen name="sign-in" options={{ animation: "slide_from_right" }} />
        <Stack.Screen name="invite" options={{ animation: "slide_from_right" }} />
      </Stack.Protected>
    </Stack>
  );
}

function Splash({ ready }: { ready: boolean }) {
  useEffect(() => {
    if (ready) void SplashScreen.hideAsync();
  }, [ready]);
  return null;
}

function Shell() {
  const { boot } = useApp();
  const [fontsLoaded] = useFonts({
    Onest_400: Onest_400Regular,
    Onest_500: Onest_500Medium,
    Onest_600: Onest_600SemiBold,
    Onest_700: Onest_700Bold,
    Onest_800: Onest_800ExtraBold,
  });
  const ready = fontsLoaded && boot !== "starting";
  return (
    <>
      <Splash ready={ready} />
      {ready ? <Gate /> : null}
    </>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <AppProvider>
          <StatusBar style="dark" />
          <Shell />
        </AppProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
