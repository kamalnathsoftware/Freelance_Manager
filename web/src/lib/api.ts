import { ApiClient, type TokenPair, type TokenStore } from "@fm/shared";

const KEY = "fm.tokens";

// Tokens live in localStorage for the web client. For production, prefer httpOnly cookies via a BFF route.
const store: TokenStore = {
  get() {
    if (typeof window === "undefined") return null;
    try { return JSON.parse(localStorage.getItem(KEY) ?? "null") as TokenPair | null; } catch { return null; }
  },
  set(t) {
    if (typeof window === "undefined") return;
    if (t) localStorage.setItem(KEY, JSON.stringify(t)); else localStorage.removeItem(KEY);
  },
};

export const api = new ApiClient(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000", store, () => {
  if (typeof window !== "undefined") window.location.href = "/login";
});
export const hasSession = () => store.get() !== null;
