import { ApiClient, type TokenPair } from "@fm/shared";
import { describe, expect, it, vi } from "vitest";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("ApiClient", () => {
  it("refreshes the token once on 401 and retries", async () => {
    let tokens: TokenPair | null = { access_token: "old", refresh_token: "r1", token_type: "bearer" };
    const store = { get: () => tokens, set: (t: TokenPair | null) => { tokens = t; } };
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      const auth = (init.headers as Record<string, string>).Authorization;
      if (url.endsWith("/auth/refresh")) return json({ access_token: "new", refresh_token: "r2", token_type: "bearer" });
      return auth === "Bearer new" ? json({ email: "a@b.c" }) : json({ error: { code: "http_401", message: "no" } }, 401);
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = new ApiClient("http://x", store);
    const [a, b] = await Promise.all([api.me(), api.me()]);
    expect(a).toEqual({ email: "a@b.c" });
    expect(b).toEqual({ email: "a@b.c" });
    expect(tokens?.refresh_token).toBe("r2");
    expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"))).toHaveLength(1);
  });

  it("clears tokens and calls onLoggedOut when refresh fails", async () => {
    let tokens: TokenPair | null = { access_token: "old", refresh_token: "r1", token_type: "bearer" };
    const out = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => json({ error: { code: "http_401", message: "no" } }, 401)));
    const api = new ApiClient("http://x", { get: () => tokens, set: (t) => { tokens = t; } }, out);
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(tokens).toBeNull();
    expect(out).toHaveBeenCalled();
  });
});
