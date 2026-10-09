import AsyncStorage from "@react-native-async-storage/async-storage";

/** Tiny offline layer: cached reads (stale-while-revalidate) and a queue of replies to send when back online. */
export async function cached<T>(key: string, fetcher: () => Promise<T>): Promise<{ data: T; stale: boolean }> {
  try {
    const data = await fetcher();
    await AsyncStorage.setItem(`cache:${key}`, JSON.stringify(data));
    return { data, stale: false };
  } catch (e) {
    const raw = await AsyncStorage.getItem(`cache:${key}`);
    if (raw) return { data: JSON.parse(raw) as T, stale: true };
    throw e;
  }
}

export interface QueuedReply { conversationId: string; body: string; key: string }
const QUEUE = "queue:replies";

export async function queuedReplies(): Promise<QueuedReply[]> {
  return JSON.parse((await AsyncStorage.getItem(QUEUE)) ?? "[]") as QueuedReply[];
}
export async function enqueueReply(r: Omit<QueuedReply, "key">) {
  const q = await queuedReplies();
  q.push({ ...r, key: `${Date.now()}-${Math.random().toString(36).slice(2)}` });
  await AsyncStorage.setItem(QUEUE, JSON.stringify(q));
}
/** Sends queued replies; the idempotency key makes retries safe. Returns how many were delivered. */
export async function flushQueue(send: (r: QueuedReply) => Promise<void>): Promise<number> {
  const q = await queuedReplies();
  const left: QueuedReply[] = [];
  let sent = 0;
  for (const r of q) {
    try { await send(r); sent++; } catch { left.push(r); }
  }
  await AsyncStorage.setItem(QUEUE, JSON.stringify(left));
  return sent;
}
