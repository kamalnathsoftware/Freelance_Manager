// Hand-maintained until `npm run generate` produces src/schema.d.ts from the OpenAPI schema.
export interface TokenPair { access_token: string; refresh_token: string; token_type: string }
export interface LoginOut { mfa_required: boolean; mfa_token: string | null; tokens: TokenPair | null }
export interface User {
  id: string; email: string; full_name: string; timezone: string; locale: string;
  email_verified: boolean; totp_enabled: boolean; settings: Record<string, unknown>; created_at: string;
}
export interface SessionInfo {
  id: string; user_agent: string; ip: string; created_at: string; last_used_at: string; current: boolean;
}
export interface AuditEntry { id: string; action: string; ip: string; meta: Record<string, unknown>; created_at: string }
export interface ApiErrorBody { error: { code: string; message: string; details: unknown } }

export interface PlatformInfo { key: string; name: string; tier: string; capabilities: string[]; rules: Record<string, number>; deep_links: Record<string, string> }
export interface PlatformAccount {
  id: string; platform: string; label: string; username: string; profile_url: string;
  mode: "api" | "email" | "manual"; status: string; last_synced_at: string | null; last_error: string;
  stats: Record<string, number>; integration_status: string;
}
export interface SyncLog { id: string; kind: string; status: string; message: string; started_at: string; finished_at: string | null }
export interface MasterProfile {
  name: string; headline: string; bio: string; skills: string[]; languages: string[]; hourly_rate: number | null;
  currency: string; location: string; timezone: string; availability: string;
  certifications: Record<string, unknown>[]; education: Record<string, unknown>[]; experience: Record<string, unknown>[];
}
export interface Completeness { score: number; checklist: { item: string; done: boolean }[] }
export interface PlatformProfile {
  account_id: string; platform: string; headline: string; bio: string; skills: string[]; hourly_rate: number | null;
  sync_status: "in_sync" | "drifted" | "missing"; rules: Record<string, number>; violations: string[];
}
export interface GigPackage { tier: "basic" | "standard" | "premium"; name: string; description: string; price: number; delivery_days: number; revisions: number; features: string[] }
export type GigStatus = "draft" | "ready" | "live" | "paused";
export interface Gig {
  id: string; title: string; category: string; tags: string[]; description: string; faq: { q: string; a: string }[];
  gallery: string[]; notes: string; keywords: string[]; status: GigStatus; packages: GigPackage[];
}
export type GigInput = Omit<Gig, "id">;
export interface Suggestion { text: string; ai_generated: boolean; requires_approval: boolean }
