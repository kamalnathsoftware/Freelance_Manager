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
