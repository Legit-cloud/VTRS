import Constants from "expo-constants";

/**
 * Where the API lives. Set EXPO_PUBLIC_API_URL when building; the Android emulator reaches the
 * host machine at 10.0.2.2, a real phone needs the machine's address or the staging URL.
 */
export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? "http://10.0.2.2:8000").replace(
  /\/$/,
  "",
);

export const APP_VERSION = Constants.expoConfig?.version ?? "1.0.0";
