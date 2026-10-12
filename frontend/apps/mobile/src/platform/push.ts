import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import type { Endpoints } from "@vtrs/core";

/**
 * Push is for one thing an agent cares about: a result was sent back for correction. Alerts
 * show while the app is open, and tapping one opens the Outbox.
 *
 * The API sends through Firebase Cloud Messaging, so only the native FCM token is useful.
 * iOS hands out an APNs token instead; until the app is built with the Firebase SDK, iOS
 * agents rely on the Outbox and the pull-to-refresh.
 */
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

export async function ensureChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync("default", {
    name: "Result updates",
    importance: Notifications.AndroidImportance.HIGH,
  });
}

/**
 * Ask once, then register the device token with the server. Quietly does nothing when the
 * agent says no, on iOS, or when the build has no Firebase configuration: capture and sync
 * never depend on it.
 */
export async function registerForPush(
  ep: Pick<Endpoints, "me">,
  alreadyRegistered: string | null,
): Promise<string | null> {
  try {
    if (Platform.OS !== "android") return null;
    await ensureChannel();
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== "granted") {
      ({ status } = await Notifications.requestPermissionsAsync());
    }
    if (status !== "granted") return null;
    const token = (await Notifications.getDevicePushTokenAsync()).data;
    if (typeof token !== "string" || token.length < 8 || token === alreadyRegistered) return null;
    await ep.me.registerPushToken(token);
    return token;
  } catch {
    return null;
  }
}

/** Call `onOpen` when an agent taps a notification. Returns the unsubscribe. */
export function onNotificationTap(onOpen: () => void): () => void {
  const subscription = Notifications.addNotificationResponseReceivedListener(() => onOpen());
  return () => subscription.remove();
}

/** Tokens rotate; keep the server's copy current. */
export function onTokenChange(handler: (token: string) => void): () => void {
  const subscription = Notifications.addPushTokenListener((token) => {
    if (typeof token.data === "string") handler(token.data);
  });
  return () => subscription.remove();
}
