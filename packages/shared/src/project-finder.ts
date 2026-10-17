// Types for the Project Finder module (/api/v1/project-finder). Hand-maintained like types.ts.
export const LEAD_STATUSES = ["new", "contacted", "replied", "call_booked", "proposal_sent", "won", "lost"] as const;
export type LeadStatus = (typeof LEAD_STATUSES)[number];
export const LEAD_STATUS_LABEL: Record<LeadStatus, string> = {
  new: "New", contacted: "Contacted", replied: "Replied", call_booked: "Call booked", proposal_sent: "Proposal sent", won: "Won", lost: "Lost",
};

export interface PFSettings {
  skills: string[]; include_keywords: string[]; exclude_keywords: string[]; min_store_score: number; daily_goal: number;
  my_name: string; home_tz: string; work_start_hour: number; work_end_hour: number; created_at: string;
}
export type PFSettingsInput = Partial<Omit<PFSettings, "created_at">>;

export interface PFLead {
  id: string; business_name: string; contact_name: string; email: string; linkedin_url: string; website: string;
  problem: string; notes: string; source: string; status: LeadStatus; next_follow_up: string | null; last_contacted_at: string | null;
  country: string; timezone: string; currency: string; job_id: string | null; created_at: string; updated_at: string; follow_up_due: boolean;
  tz_overlap: PFTzOverlap | null;
}
export type PFLeadInput = Partial<Omit<PFLead, "id" | "created_at" | "updated_at" | "last_contacted_at" | "follow_up_due" | "tz_overlap">> & { business_name: string };
export type PFLeadPatch = Partial<PFLeadInput>;

export type OutreachChannel = "email" | "linkedin" | "other";
export interface PFGoal {
  goal: number; today: number; remaining: number; goal_met: boolean; streak: number; best_streak: number;
  days: { date: string; count: number; met: boolean }[];
}

export const TEMPLATE_KINDS = ["cold_email", "linkedin_dm", "proposal"] as const;
export type TemplateKind = (typeof TEMPLATE_KINDS)[number];
export const TEMPLATE_KIND_LABEL: Record<TemplateKind, string> = { cold_email: "Cold email", linkedin_dm: "LinkedIn DM", proposal: "Proposal" };
export interface PFTemplate { id: string; name: string; kind: TemplateKind; subject: string; body: string; created_at: string }
export type PFTemplateInput = Pick<PFTemplate, "name" | "kind" | "subject" | "body">;
export interface PFDraft { subject: string; body: string; missing: string[]; unknown: string[]; ai_generated: boolean }

export interface PFSource {
  id: string; key: string; name: string; url: string; kind: "feed" | "manual"; builtin: boolean; status: "active" | "paused";
  last_checked_at: string | null; last_result: string; notes: string; hint: string;
}
export type JobStatus = "new" | "saved" | "dismissed";
export interface PFJob {
  id: string; source_key: string; source_name: string; title: string; company: string; description: string; budget: string;
  budget_min: number | null; budget_max: number | null; currency: string; url: string; posted_at: string | null; remote: boolean;
  skills: string[]; fit_score: number; score_reasons: string[]; status: JobStatus; created_at: string;
}
export interface PFJobQuery {
  q?: string; keywords?: string; source?: string; min_score?: number; remote?: boolean; status?: "active" | JobStatus; sort?: "score" | "date"; limit?: number;
}
export interface PFRefreshResult { key: string; name: string; status: "ok" | "error" | "skipped" | "paused"; fetched: number; new: number; message: string }

export interface PFTzOverlap {
  home_tz: string; client_tz: string; home_offset: string; client_offset: string; difference_hours: number; overlap_hours: number;
  windows: { home_start: string; home_end: string; client_start: string; client_end: string }[];
  rating: "good" | "workable" | "limited" | "none"; note: string; home_now: string; client_now: string; client_day_in_home_time: string; hours: string;
}

export const PROPOSAL_STATUSES = ["sent", "replied", "interview", "won", "lost", "no_response"] as const;
export type ProposalStatus = (typeof PROPOSAL_STATUSES)[number];
export const PROPOSAL_STATUS_LABEL: Record<ProposalStatus, string> = { sent: "Sent", replied: "Replied", interview: "Interview", won: "Won", lost: "Lost", no_response: "No response" };
export interface PFProposal {
  id: string; title: string; lead_id: string | null; lead_name: string; job_id: string | null; source: string; sent_on: string; amount: number | null;
  currency: string; status: ProposalStatus; replied_on: string | null; outcome: string; created_at: string; replied: boolean; days_waiting: number | null;
}
export interface PFProposalInput {
  title?: string; lead_id?: string | null; job_id?: string | null; source?: string; sent_on?: string | null; amount?: number | null;
  currency?: string; status?: ProposalStatus; replied_on?: string | null; outcome?: string;
}

export interface PFSourceStat { source: string; sent: number; replied: number; won: number; lost: number; reply_rate: number | null; win_rate: number | null; earnings: Record<string, number> }
export interface PFStats {
  days: number | null;
  proposals: Omit<PFSourceStat, "source"> & { pending: number };
  by_source: PFSourceStat[];
  best_source: { source: string; reason: string; rule: string } | null;
  earnings_basis: string;
  leads: { total: number; by_status: Record<LeadStatus, number>; follow_ups_due: number; win_rate: number | null; by_source: { source: string; leads: number; won: number }[] };
  foreign: { invoices: number; firc_pending: number; invoiced: Record<string, number>; countries: string[] };
  outreach: { last_7_days: number; last_30_days: number; today: number; goal: number; streak: number; best_streak: number };
}

export const PAYMENT_METHODS = ["wise", "payoneer", "paypal", "swift", "other"] as const;
export type PaymentMethod = (typeof PAYMENT_METHODS)[number];
export interface PFInvoice {
  id: string; lead_id: string; lead_name: string; reference: string; amount: number; currency: string; invoice_date: string;
  payment_method: PaymentMethod; firc_received: boolean; lut_note: string; created_at: string;
}
export interface PFInvoiceInput {
  lead_id: string; amount: number; reference?: string; currency?: string; invoice_date?: string | null; payment_method?: PaymentMethod; firc_received?: boolean; lut_note?: string;
}
