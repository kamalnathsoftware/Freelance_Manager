import AsyncStorage from "@react-native-async-storage/async-storage";
import { cached, enqueueReply, flushQueue, queuedReplies } from "../src/offline";

jest.mock("@react-native-async-storage/async-storage", () => require("@react-native-async-storage/async-storage/jest/async-storage-mock"));

beforeEach(async () => { await AsyncStorage.clear(); });

describe("offline cache", () => {
  it("returns fresh data and caches it", async () => {
    const r = await cached("k", async () => [1, 2]);
    expect(r).toEqual({ data: [1, 2], stale: false });
  });
  it("falls back to the cached copy (marked stale) when the network fails", async () => {
    await cached("k", async () => ["saved"]);
    const r = await cached<string[]>("k", async () => { throw new Error("offline"); });
    expect(r).toEqual({ data: ["saved"], stale: true });
  });
  it("rethrows when there is nothing cached", async () => {
    await expect(cached("none", async () => { throw new Error("offline"); })).rejects.toThrow("offline");
  });
});

describe("reply queue", () => {
  it("keeps failed sends and removes delivered ones, with stable idempotency keys", async () => {
    await enqueueReply({ conversationId: "a", body: "one" });
    await enqueueReply({ conversationId: "b", body: "two" });
    const keys = (await queuedReplies()).map((q) => q.key);
    expect(new Set(keys).size).toBe(2);
    const sent = await flushQueue(async (r) => { if (r.conversationId === "b") throw new Error("still offline"); });
    expect(sent).toBe(1);
    const left = await queuedReplies();
    expect(left).toHaveLength(1);
    expect(left[0].key).toBe(keys[1]); // same key on retry => server dedupes
  });
});
