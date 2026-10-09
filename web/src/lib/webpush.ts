import { api } from "./api";

const b64 = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

/** Ask permission and register this browser for push. Returns false if unsupported or not configured. */
export async function enableWebPush(): Promise<boolean> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return false;
  const { public_key } = await api.vapidKey();
  if (!public_key) return false;
  if ((await Notification.requestPermission()) !== "granted") return false;
  const reg = await navigator.serviceWorker.register("/sw.js");
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(public_key) });
  await api.registerDevice({ kind: "webpush", token: JSON.stringify(sub.toJSON()), label: navigator.userAgent.slice(0, 80) });
  return true;
}
