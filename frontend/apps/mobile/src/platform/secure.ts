import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const KEYS = {
  refresh: "vtrs.refresh_token",
  device: "vtrs.device_id",
  phone: "vtrs.phone",
} as const;

// The keychain does not exist in a browser. The web build is only a preview of the screens, so
// it keeps these in localStorage; the phone builds never take this path.
const web = Platform.OS === "web";

function local(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * The refresh token and the device id never leave the keychain. Reads fail soft: a missing or
 * unreadable value just means "not signed in".
 */
export const secure = {
  async get(key: keyof typeof KEYS): Promise<string | null> {
    if (web) return local()?.getItem(KEYS[key]) ?? null;
    try {
      return await SecureStore.getItemAsync(KEYS[key]);
    } catch {
      return null;
    }
  },
  async set(key: keyof typeof KEYS, value: string): Promise<void> {
    if (web) {
      local()?.setItem(KEYS[key], value);
      return;
    }
    await SecureStore.setItemAsync(KEYS[key], value, {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
    });
  },
  /** Sign out: forget the session, keep the device id the server bound to this phone. */
  async clear(): Promise<void> {
    if (web) {
      local()?.removeItem(KEYS.refresh);
      return;
    }
    await SecureStore.deleteItemAsync(KEYS.refresh).catch(() => undefined);
  },
};
