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

export interface Job {
  id: string; platform: string; title: string; description: string; budget_min: number | null; budget_max: number | null;
  budget_type: "fixed" | "hourly"; currency: string; skills: string[]; client: Record<string, unknown>; url: string;
  posted_at: string | null; source: string; score: number; score_reasons: string[]; dismissed: boolean; created_at: string;
}
export interface JobInput {
  platform: string; title: string; description?: string; budget_min?: number | null; budget_max?: number | null;
  budget_type?: "fixed" | "hourly"; skills?: string[]; url?: string; client?: Record<string, unknown>;
}
export type Stage = "found" | "shortlisted" | "drafted" | "submitted" | "viewed" | "interview" | "won" | "lost";
export const STAGES: Stage[] = ["found", "shortlisted", "drafted", "submitted", "viewed", "interview", "won", "lost"];
export interface Proposal {
  id: string; job_id: string; account_id: string | null; template_id: string | null; stage: Stage; position: number;
  body: string; bid_amount: number | null; currency: string; credits_used: number; ai_generated: boolean;
  approved_at: string | null; submitted_at: string | null; submitted_via: string; lost_reason: string;
  follow_up_at: string | null; job_title: string; platform: string; unresolved_variables: string[];
}
export interface ProposalTemplate { id: string; name: string; body: string; platform: string }
export interface SavedSearch { id: string; name: string; keywords: string[]; skills: string[]; platforms: string[]; min_budget: number | null; alert_min_score: number; active: boolean }
export interface SubmitResult { submitted: boolean; via: "api" | "manual"; proposal_text?: string; open_url?: string; instructions?: string }
export interface ApiKeyInfo { id: string; name: string; prefix: string; last_used_at: string | null; revoked: boolean; created_at: string }
export interface PlatformEvent { id: string; platform: string; kind: string; title: string; summary: string; url: string; source: string; handled: boolean; received_at: string }
export interface ProposalAnalytics {
  submitted: number; won: number; win_rate: number;
  by_platform: { key: string; submitted: number; won: number; win_rate: number }[];
  by_template: { key: string; submitted: number; won: number; win_rate: number }[];
  by_price_band: { key: string; submitted: number; won: number; win_rate: number }[];
  by_hour: { key: string; submitted: number; won: number; win_rate: number }[];
}
