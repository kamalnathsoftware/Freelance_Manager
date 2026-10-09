import type {
  ApiErrorBody, AuditEntry, Completeness, Gig, GigInput, LoginOut, MasterProfile, PlatformAccount, PlatformInfo,
  PlatformProfile, SessionInfo, Suggestion, SyncLog, TokenPair, User,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export interface TokenStore {
  get(): Promise<TokenPair | null> | TokenPair | null;
  set(t: TokenPair | null): Promise<void> | void;
}

/** Framework-agnostic API client with transparent refresh-token rotation. Used by web and mobile. */
export class ApiClient {
  private refreshing: Promise<TokenPair | null> | null = null;
  constructor(private baseUrl: string, private store: TokenStore, private onLoggedOut?: () => void) {}

  private async raw(path: string, init: RequestInit, token?: string): Promise<Response> {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as object) };
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(`${this.baseUrl}/api/v1${path}`, { ...init, headers });
  }

  private async refresh(): Promise<TokenPair | null> {
    if (!this.refreshing) {
      this.refreshing = (async () => {
        const cur = await this.store.get();
        if (!cur) return null;
        const r = await this.raw("/auth/refresh", { method: "POST", body: JSON.stringify({ refresh_token: cur.refresh_token }) });
        if (!r.ok) { await this.store.set(null); this.onLoggedOut?.(); return null; }
        const t = (await r.json()) as TokenPair;
        await this.store.set(t);
        return t;
      })().finally(() => { this.refreshing = null; });
    }
    return this.refreshing;
  }

  async request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
    let tokens = auth ? await this.store.get() : null;
    let res = await this.raw(path, init, tokens?.access_token);
    if (res.status === 401 && auth && tokens) {
      tokens = await this.refresh();
      if (tokens) res = await this.raw(path, init, tokens.access_token);
    }
    if (!res.ok) {
      let body: ApiErrorBody | null = null;
      try { body = await res.json(); } catch { /* non-JSON error */ }
      throw new ApiError(res.status, body?.error.code ?? "unknown", body?.error.message ?? res.statusText, body?.error.details);
    }
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  private post<T>(path: string, body?: unknown, auth = true) {
    return this.request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }, auth);
  }

  // auth
  signup = async (b: { email: string; password: string; full_name?: string }) => {
    const t = await this.post<TokenPair>("/auth/signup", b, false); await this.store.set(t); return t;
  };
  login = async (b: { email: string; password: string }) => {
    const r = await this.post<LoginOut>("/auth/login", b, false);
    if (r.tokens) await this.store.set(r.tokens);
    return r;
  };
  login2fa = async (mfa_token: string, code: string) => {
    const t = await this.post<TokenPair>("/auth/login/2fa", { mfa_token, code }, false); await this.store.set(t); return t;
  };
  logout = async () => { try { await this.post("/auth/logout"); } finally { await this.store.set(null); } };
  forgotPassword = (email: string) => this.post("/auth/forgot-password", { email }, false);
  resetPassword = (token: string, new_password: string) => this.post("/auth/reset-password", { token, new_password }, false);
  verifyEmail = (token: string) => this.post("/auth/verify-email", { token }, false);

  // account
  me = () => this.request<User>("/me");
  updateMe = (b: Partial<Pick<User, "full_name" | "timezone" | "locale" | "settings">>) =>
    this.request<User>("/me", { method: "PATCH", body: JSON.stringify(b) });
  sessions = () => this.request<SessionInfo[]>("/me/sessions");
  revokeSession = (id: string) => this.request(`/me/sessions/${id}`, { method: "DELETE" });
  auditLog = () => this.request<AuditEntry[]>("/me/audit-log");
  setup2fa = () => this.post<{ secret: string; otpauth_uri: string }>("/me/2fa/setup");
  enable2fa = (code: string) => this.post("/me/2fa/enable", { code });
  disable2fa = (code: string) => this.post("/me/2fa/disable", { code });
  exportData = () => this.request<Record<string, unknown>>("/me/export");

  // platforms
  platformCatalog = () => this.request<PlatformInfo[]>("/platforms/catalog");
  accounts = () => this.request<PlatformAccount[]>("/platforms/accounts");
  addAccount = (b: { platform: string; label?: string; username?: string; profile_url?: string }) => this.post<PlatformAccount>("/platforms/accounts", b);
  updateAccount = (id: string, b: Partial<Pick<PlatformAccount, "label" | "username" | "profile_url" | "stats">>) =>
    this.request<PlatformAccount>(`/platforms/accounts/${id}`, { method: "PATCH", body: JSON.stringify(b) });
  connectToken = (id: string, access_token: string) =>
    this.request<PlatformAccount>(`/platforms/accounts/${id}/token`, { method: "PUT", body: JSON.stringify({ access_token }) });
  removeAccount = (id: string) => this.request(`/platforms/accounts/${id}`, { method: "DELETE" });
  syncAccount = (id: string) => this.post<SyncLog>(`/platforms/accounts/${id}/sync`);
  syncLogs = (id: string) => this.request<SyncLog[]>(`/platforms/accounts/${id}/logs`);

  // profiles
  master = () => this.request<MasterProfile | null>("/profile/master");
  saveMaster = (b: MasterProfile) => this.request<MasterProfile>("/profile/master", { method: "PUT", body: JSON.stringify(b) });
  completeness = (platform?: string) => this.request<Completeness>(`/profile/completeness${platform ? `?platform=${platform}` : ""}`);
  platformProfiles = () => this.request<PlatformProfile[]>("/profile/platforms");
  derivePlatformProfile = (accountId: string) => this.post<PlatformProfile>(`/profile/platforms/${accountId}/derive`);
  editPlatformProfile = (accountId: string, b: Partial<Pick<PlatformProfile, "headline" | "bio" | "skills" | "hourly_rate">>) =>
    this.request<PlatformProfile>(`/profile/platforms/${accountId}`, { method: "PATCH", body: JSON.stringify(b) });

  // gigs
  gigs = () => this.request<Gig[]>("/gigs");
  createGig = (b: GigInput) => this.post<Gig>("/gigs", b);
  updateGig = (id: string, b: GigInput) => this.request<Gig>(`/gigs/${id}`, { method: "PUT", body: JSON.stringify(b) });
  deleteGig = (id: string) => this.request(`/gigs/${id}`, { method: "DELETE" });
  cloneGig = (id: string, account_ids: string[]) => this.post(`/gigs/${id}/clone`, { account_ids });

  // AI (suggestions only — caller must get user approval before saving)
  aiRewrite = (b: { kind: "headline" | "bio" | "gig_title" | "gig_description"; text: string; platform?: string; tone?: string; keywords?: string[] }) =>
    this.post<Suggestion>("/ai/rewrite", b);
}
