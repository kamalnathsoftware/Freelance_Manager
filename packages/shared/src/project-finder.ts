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
}
export type PFLeadInput = Partial<Omit<PFLead, "id" | "created_at" | "updated_at" | "last_contacted_at" | "follow_up_due">> & { business_name: string };
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
