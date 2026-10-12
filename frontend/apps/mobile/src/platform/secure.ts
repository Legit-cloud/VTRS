import * as SecureStore from "expo-secure-store";

const KEYS = {
  refresh: "vtrs.refresh_token",
  device: "vtrs.device_id",
  phone: "vtrs.phone",
} as const;

/**
 * The refresh token and the device id never leave the keychain. Reads fail soft: a missing or
 * unreadable value just means "not signed in".
 */
export const secure = {
  async get(key: keyof typeof KEYS): Promise<string | null> {
    try {
      return await SecureStore.getItemAsync(KEYS[key]);
    } catch {
      return null;
    }
  },
  async set(key: keyof typeof KEYS, value: string): Promise<void> {
    await SecureStore.setItemAsync(KEYS[key], value, {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
    });
  },
  /** Sign out: forget the session, keep the device id the server bound to this phone. */
  async clear(): Promise<void> {
    await SecureStore.deleteItemAsync(KEYS.refresh).catch(() => undefined);
  },
};
