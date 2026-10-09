# Progress

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: monorepo, Docker, CI, auth, settings, design system, app shells, API client | ✅ Done |
| 2 | Platform hub, profiles, gigs, AI rewrite | ⏳ Next |
| 3 | Jobs, proposals, pipeline, browser extension, email ingestion | ⏳ |
| 4 | Unified inbox, real-time, CRM | ⏳ |
| 5 | Notifications (in-app, push, email, WhatsApp, …) | ⏳ |
| 6 | Orders, projects, time, invoices, finance | ⏳ |
| 7 | Forms builder, automation rules, AI assistant | ⏳ |
| 8 | Analytics, goals, polish, a11y, docs | ⏳ |

## Phase 1 — what exists

**Backend** (19 tests, 95% coverage, ruff + mypy clean): signup/login, access+refresh JWT with rotation and reuse detection, email verification, password reset, change password, TOTP 2FA (secret encrypted with Fernet), Google login (ID-token verification; needs `GOOGLE_CLIENT_ID`), session list/revoke, audit log, GDPR export + account deletion, rate limiting, CORS, consistent error format, `/health`, Alembic migration, Celery app skeleton.

**Web**: login/signup/forgot-password, collapsible sidebar shell, Cmd/Ctrl+K palette, dark/light theme, toasts, skeletons, empty states, dashboard (KPIs, charts — placeholder data), settings (2FA, sessions, data export), PWA manifest. Vitest + RTL tests; builds clean.

**Mobile**: Expo Router tabs (Home/Inbox/Jobs/Projects/More), login with 2FA, SecureStore tokens, biometric unlock, pull-to-refresh. Type-checks clean (not run on a device in this environment).

**Shared**: framework-agnostic `ApiClient` with single-flight refresh, Zod schemas, design tokens.

## Not yet done / known gaps from Phase 1
- Team members/VA roles: table exists, no invite/permission endpoints yet.
- Web push, Storybook, Playwright smoke tests, WebSocket channel: planned for later phases.
- Web stores tokens in localStorage; a cookie-based BFF is recommended before production.
- Rate limiter is in-process; move to Redis for multi-replica deployments.
- Dashboard numbers are placeholders until the analytics phase.
