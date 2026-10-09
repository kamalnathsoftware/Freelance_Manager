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

const WS_KEY = "fm.workspace";
/** The workspace (owner id) the user is currently acting in; null = their own. */
export const getWorkspace = (): string | null => {
  try { return typeof window === "undefined" ? null : localStorage.getItem(WS_KEY); } catch { return null; }
};
export const setWorkspace = (id: string | null) => {
  try { if (id) localStorage.setItem(WS_KEY, id); else localStorage.removeItem(WS_KEY); } catch { /* storage unavailable */ }
};

export const api = new ApiClient(
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  store,
  () => { if (typeof window !== "undefined") window.location.href = "/login"; },
  getWorkspace,
);
export const hasSession = () => store.get() !== null;
