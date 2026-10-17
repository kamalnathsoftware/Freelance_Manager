import { ApiError } from "@fm/shared";

/** Server validation errors ({loc, msg}[]) -> { field: message } so forms can show them inline. */
export function fieldErrors(e: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (e instanceof ApiError && Array.isArray(e.details)) {
    for (const d of e.details as { loc?: (string | number)[]; msg?: string }[]) {
      const field = d.loc?.[d.loc.length - 1];
      if (typeof field === "string" && d.msg) out[field] = d.msg.replace(/^Value error, /, "");
    }
  }
  return out;
}

export const errMsg = (e: unknown, fallback = "Something went wrong") => (e instanceof ApiError ? e.message : fallback);

export const COMMON_TIMEZONES = [
  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Toronto", "America/Sao_Paulo",
  "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Amsterdam", "Europe/Stockholm", "Asia/Dubai", "Asia/Singapore",
  "Asia/Tokyo", "Australia/Sydney", "Pacific/Auckland", "Africa/Johannesburg", "Asia/Kolkata",
];
export const LEAD_SOURCES = ["Cold email", "LinkedIn", "Reddit r/forhire", "Hacker News", "Referral", "Website contact form", "Other"];

/** Local calendar day as YYYY-MM-DD (not UTC), for comparing with server dates. */
export const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
