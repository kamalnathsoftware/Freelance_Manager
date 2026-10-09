import Constants from "expo-constants";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "@/api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowAlert: true, shouldPlaySound: false, shouldSetBadge: true }),
});

/** Registers this device for push (Expo -> FCM/APNs). Safe to call on every launch; the server dedupes the token. */
export async function registerForPush(): Promise<string | null> {
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", { name: "Default", importance: Notifications.AndroidImportance.HIGH });
  }
  const existing = await Notifications.getPermissionsAsync();
  const status = existing.granted ? existing : await Notifications.requestPermissionsAsync();
  if (!status.granted) return null;
  const projectId = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId;
  try {
    const { data } = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
    await api.registerDevice({ kind: "expo", token: data, label: Platform.OS });
    return data;
  } catch {
    return null; // simulator / no projectId: push simply isn't available
  }
}
