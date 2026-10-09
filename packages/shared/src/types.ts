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

export type ConvStatus = "open" | "snoozed" | "archived";
export interface Conversation {
  id: string; platform: string; subject: string; platform_url: string; client_id: string | null; status: ConvStatus;
  starred: boolean; labels: string[]; assignee_id: string | null; snoozed_until: string | null; unread_count: number;
  last_message_at: string; last_preview: string; awaiting_reply_since: string | null; client_name: string; client_vip: boolean;
}
export interface ChatMessage {
  id: string; direction: "in" | "out"; sender_name: string; body: string; source: string;
  delivery: "sent" | "pending_manual" | "failed"; ai_generated: boolean; response_seconds: number | null; created_at: string;
  attachments: { filename: string; url: string; content_type?: string; size?: number }[];
}
export interface SendResult { message: ChatMessage; duplicate: boolean; requires_manual_paste: boolean; reply_on_platform_url: string | null }
export interface SlaAlerts { sla_minutes: number; alerts: { conversation_id: string; platform: string; subject: string; waiting_minutes: number; vip: boolean }[] }
export interface CannedResponse { id: string; shortcut: string; body: string }
export interface Client {
  id: string; name: string; email: string; company: string; country: string; timezone: string; notes: string; tags: string[];
  vip: boolean; total_earned: number; completed_orders: number; identities: { id: string; platform: string; handle: string }[];
  lifetime_value: number; repeat_client: boolean; won_proposals: number;
}
export type ClientInput = Omit<Client, "id" | "identities" | "lifetime_value" | "repeat_client" | "won_proposals">;
export interface SearchResults { [group: string]: { id: string; title: string; subtitle: string; href: string }[] }
export interface RealtimeEvent { event: string; data: Record<string, unknown> }

export interface AppNotification { id: string; type: string; title: string; body: string; url: string; priority: string; read_at: string | null; created_at: string }
export interface Delivery { id: string; event_id: string; channel: string; status: string; attempts: number; error: string; mode: string; next_attempt_at: string | null; fallback_of: string | null; sent_at: string | null; created_at: string; event_title: string }
export interface NotificationPrefs {
  event_types: { type: string; label: string }[]; channels: string[];
  matrix: Record<string, Record<string, { enabled: boolean; mode: "instant" | "hourly" | "daily" }>>;
  settings: { quiet_start: string; quiet_end: string; digest_hour: number; fallback: Record<string, string> };
}
export interface ChannelInfo { channel: string; address: string; opted_in: boolean; server_configured: boolean }

export interface Milestone { id: string; title: string; amount: number; due_at: string | null; status: string; paid_at: string | null }
export interface Order {
  id: string; platform: string; external_ref: string | null; title: string; description: string; amount: number; currency: string;
  status: "pending" | "active" | "delivered" | "revision" | "completed" | "cancelled"; client_id: string | null; due_at: string | null;
  revisions_allowed: number; revisions_used: number; over_revision_limit: boolean; checklist: { item: string; done: boolean }[];
  milestones: Milestone[]; files: { id: string; filename: string; url: string; kind: string }[]; client_name: string; project_id: string | null;
}
export interface Project { id: string; name: string; description: string; status: string; hourly_rate: number | null; currency: string; hours_tracked: number; tasks_total: number; tasks_done: number }
export interface Task { id: string; project_id: string; title: string; status: "todo" | "doing" | "done"; priority: string; due_at: string | null; position: number }
export interface TimeEntry { id: string; project_id: string | null; started_at: string; ended_at: string | null; note: string; billable: boolean; invoice_id: string | null; minutes: number }
export interface InvoiceItem { description: string; quantity: number; unit_price: number }
export interface Invoice {
  id: string; number: string; currency: string; status: "draft" | "sent" | "paid" | "void"; issue_date: string; due_date: string | null;
  items: InvoiceItem[]; tax_pct: number; subtotal: number; tax_amount: number; total: number; overdue: boolean; client_name: string; client_id: string | null;
}
export interface Expense { id: string; spent_on: string; amount: number; currency: string; category: string; description: string; tax_deductible: boolean }
export interface Payment { id: string; platform: string; source: string; gross: number; fee: number; net: number; currency: string; received_on: string; note: string }
export interface EarningsReport {
  currency: string; rows: { key: string; gross: number; fee: number; net: number; count: number }[];
  totals: { gross: number; fees: number; net: number; expenses: number; profit: number };
  expenses_by_category: Record<string, number>; tax: { rate_pct: number; taxable_income: number; estimated_tax: number; disclaimer: string }; missing_fx_rates: string[];
}
export interface FinanceSummary { currency: string; month: EarningsReport["totals"]; outstanding_invoices: number; overdue_invoices: number; tax_set_aside: number; monthly_income_goal: number; goal_progress: number | null }
export interface CalendarItem { id: string; kind: string; title: string; start: string; end: string | null; all_day: boolean; href: string }

export type FieldType = "text" | "textarea" | "email" | "number" | "dropdown" | "radio" | "checkbox" | "date" | "file" | "rating" | "agreement";
export interface FormFieldDef { key: string; type: FieldType; label: string; help_text?: string; required: boolean; options: string[]; show_if: { field: string; op: string; value?: unknown } | null }
export interface FormDef {
  id: string; public_key: string; title: string; description: string; kind: string; published: boolean; settings: Record<string, unknown>;
  version: number; fields: FormFieldDef[]; public_url: string; embed_snippet: string; submission_count: number;
}
export interface FormSubmission { id: string; form_id: string; submitter_name: string; submitter_email: string; answers: Record<string, unknown>; signature: Record<string, unknown> | null; result: Record<string, unknown>; created_at: string }
export interface PublicForm { title: string; description: string; kind: string; version: number; agreement_text: string; requires_signature: boolean; fields: FormFieldDef[] }
export interface AutomationRule { id: string; name: string; enabled: boolean; trigger: string; conditions: { field: string; op: string; value?: unknown }[]; actions: { type: string; params?: Record<string, unknown> }[]; run_count: number; last_run_at: string | null }
export interface AutomationMeta { triggers: { key: string; label: string }[]; operators: string[]; actions: string[]; presets: (Omit<AutomationRule, "id" | "enabled" | "run_count" | "last_run_at"> & { key: string })[] }
export interface AutomationRun { id: string; rule_id: string; trigger: string; status: string; log: string[]; created_at: string }
export interface Briefing { headline: string; facts: Record<string, unknown>; narrative: { text: string } | null }
export interface Requirements { summary: string; requirements: string[]; deliverables: string[]; deadline: string | null; budget: string | null; open_questions: string[] }

export interface Workspace { owner_id: string; name: string; email: string; role: "owner" | "full" | "messaging_only" | "view_only"; is_self: boolean }
export interface TeamMember { id: string; invite_email: string; role: "full" | "messaging_only" | "view_only"; accepted: boolean; created_at: string }
export interface AnalyticsOverview {
  currency: string; days: number; granularity: string;
  kpis: { net_earnings: number; previous_net_earnings: number; change_pct: number | null; win_rate: number; proposals_submitted: number; open_pipeline_value: number; active_orders: number; avg_response_minutes: number | null };
  earnings_series: { key: string; net: number }[];
  by_platform: { key: string; gross: number; fee: number; net: number; count: number }[];
  top_clients: { key: string; net: number }[];
  funnel: { stage: string; count: number; conversion_from_previous: number | null }[];
  win_rate_by: Record<string, { key: string; submitted: number; won: number; win_rate: number }[]>;
  response_times: { platform: string; replies: number; avg_response_minutes: number }[];
  utilization: { tracked_hours: number; billable_hours: number; capacity_hours: number; utilization_pct: number | null; billable_pct: number | null };
  upcoming_deadlines: { title: string; kind: string; at: string; href: string }[];
  missing_fx_rates: string[];
}
export interface GoalProgress {
  currency: string; goals: { monthly_income: number; yearly_income: number; weekly_hours: number };
  month: { earned: number; goal: number; pct: number | null; expected_pct_by_today: number; status: "ahead" | "on_track" | "behind" | null };
  year: { earned: number; goal: number; pct: number | null };
  forecast: { run_rate_month_end: number; committed_orders_net: number; pipeline_weighted: number; month_end_with_committed: number; month_end_with_pipeline: number; assumptions: { note: string; source?: string; stage_win_probability: Record<string, number | string> } };
}
export interface OpsOverview { db_ok: boolean; users: number; pending_deliveries: number; celery: { online: number; error?: string }; last_24h: Record<string, Record<string, number>>; recent_failures: Record<string, Record<string, unknown>[]> }
