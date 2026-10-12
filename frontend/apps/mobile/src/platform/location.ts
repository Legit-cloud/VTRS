import * as Location from "expo-location";
import type { GpsFix } from "../core/capture";

export type LocationAccess = "granted" | "denied" | "undetermined";

export async function locationAccess(): Promise<LocationAccess> {
  const { status } = await Location.getForegroundPermissionsAsync();
  return status === "granted" ? "granted" : status === "denied" ? "denied" : "undetermined";
}

export async function askForLocation(): Promise<LocationAccess> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === "granted" ? "granted" : "denied";
}

/**
 * One position, once, when a result is sent. Never tracked in the background. Resolves null
 * rather than blocking the result: a missing fix is a flag for an officer, not a reason to
 * keep the agent from sending.
 */
export async function currentFix(timeoutMs = 10_000): Promise<GpsFix | null> {
  try {
    if ((await locationAccess()) !== "granted") return null;
    const position = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs)),
    ]);
    if (!position) {
      const last = await Location.getLastKnownPositionAsync({ maxAge: 5 * 60_000 });
      return last
        ? { lat: last.coords.latitude, lng: last.coords.longitude, accuracyM: last.coords.accuracy }
        : null;
    }
    return {
      lat: position.coords.latitude,
      lng: position.coords.longitude,
      accuracyM: position.coords.accuracy,
    };
  } catch {
    return null;
  }
}
