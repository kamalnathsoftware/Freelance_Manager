# Progress

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: monorepo, Docker, CI, auth, settings, design system, app shells, API client | ✅ Done |
| 2 | Platform hub, profiles, gigs, AI rewrite | ✅ Done |
| 3 | Jobs, proposals, pipeline, browser extension, email ingestion | ✅ Done |
| 4 | Unified inbox, real-time, CRM | ⏳ Next |
| 5 | Notifications (in-app, push, email, WhatsApp, …) | ⏳ |
| 6 | Orders, projects, time, invoices, finance | ⏳ |
| 7 | Forms builder, automation rules, AI assistant | ⏳ |
| 8 | Analytics, goals, polish, a11y, docs | ⏳ |

## Phase 1 — what exists

**Backend** (19 tests, 95% coverage, ruff + mypy clean): signup/login, access+refresh JWT with rotation and reuse detection, email verification, password reset, change password, TOTP 2FA (secret encrypted with Fernet), Google login (ID-token verification; needs `GOOGLE_CLIENT_ID`), session list/revoke, audit log, GDPR export + account deletion, rate limiting, CORS, consistent error format, `/health`, Alembic migration, Celery app skeleton.

**Web**: login/signup/forgot-password, collapsible sidebar shell, Cmd/Ctrl+K palette, dark/light theme, toasts, skeletons, empty states, dashboard (KPIs, charts — placeholder data), settings (2FA, sessions, data export), PWA manifest. Vitest + RTL tests; builds clean.

**Mobile**: Expo Router tabs (Home/Inbox/Jobs/Projects/More), login with 2FA, SecureStore tokens, biometric unlock, pull-to-refresh. Type-checks clean (not run on a device in this environment).

**Shared**: framework-agnostic `ApiClient` with single-flight refresh, Zod schemas, design tokens.

## Phase 2 — what exists

**Backend** (32 tests, ~94% coverage): `PlatformAdapter` ABC + capability matrix + registry (Upwork, Freelancer.com = API tier; Fiverr, PeoplePerHour, Toptal, Guru, LinkedIn, Contra = email/manual tier; Direct). Fiverr & co. deliberately expose **no** send-message/submit-proposal capability. Platform accounts with encrypted token vault, manual/scheduled sync (Celery beat every 15 min for API accounts), sync logs + error surfacing. Master profile → per-platform variants with character-limit rules, drift detection (`in_sync`/`drifted`), diff, completeness score + checklist, encrypted contact details, portfolio CRUD. Gig manager: packages, clone to platforms (limits applied, idempotent), publish checklist, copy-ready export with deep link, performance metrics (CTR/conversion), status. AI rewrite/keywords via the Claude API — responses carry `ai_generated` + `requires_approval`. Alembic migration `0002`.

**Web**: Platforms hub (add/sync/remove, integration status), Profiles (master form, completeness, AI suggest→apply/discard, platform variants with drift), Gigs (create with 3 packages, clone, delete).

**Stubbed pending API access**: Upwork GraphQL sync (raises `NotConfiguredError`, logged as *skipped*). Freelancer.com profile sync is implemented against `/users/0.1/self` but untested against the live API. Platform field limits in `adapters/rules.py` are reasonable defaults — verify against current platform docs.

## Phase 3 — what exists

**Backend** (46 tests total, 95% coverage): job inbox (dedupe/upsert by platform+external id, filters, dismiss), explainable match scoring (skills, budget vs rate, saved-search keywords, past wins, client signals), saved searches with alert events (`job_match`), proposal templates with `{variables}`, template/AI drafting (labelled `ai_generated`), bid suggestion, kanban pipeline (8 stages, loss reasons required, follow-up reminders), connects/credits ledger, proposal analytics (win rate by platform/template/price band/hour). **Human-in-the-loop is enforced server-side**: submit/mark-submitted/move-to-submitted return 409 without a prior explicit `approve`, and editing the text revokes approval. API submission is attempted only for API-tier accounts whose adapter supports it; otherwise the response is the assisted flow (copy text + open platform link + "mark as submitted").
Email ingestion: sender/subject classifier for fiverr/upwork/freelancer/peopleperhour/toptal/guru/linkedin/contra (message, order, delivery, revision, offer, job invite, review, payment, bid viewed/accepted/declined), idempotent `PlatformEvent`s, account counters, job-invite → job. Gmail OAuth (read-only scope) connect + poll (metadata/snippet only). Scoped API keys (hash-only storage) for the extension.
**Chrome extension (MV3)** in `extension/`: on-click only (`activeTab`), reads the already-rendered page (JSON-LD/OG/h1/selection), posts to `/ingest/capture` with an ingest-only key.
**Web**: Jobs inbox (filters, match %, shortlist→builder), Pipeline kanban (drag-and-drop + keyboard select), Proposal builder (templates, AI draft, approve, assisted submit), API-key management in Settings.

**Limitations**: email patterns are heuristic and need tuning against real notification emails; Gmail poll is on-demand (no Pub/Sub push or Celery schedule yet); no Gmail token refresh; Upwork/Freelancer job feeds (`fetch_jobs`) are not implemented; the extension has no icons and uses generic page parsing.

## Not yet done / known gaps from Phase 1
- Team members/VA roles: table exists, no invite/permission endpoints yet.
- Web push, Storybook, Playwright smoke tests, WebSocket channel: planned for later phases.
- Web stores tokens in localStorage; a cookie-based BFF is recommended before production.
- Rate limiter is in-process; move to Redis for multi-replica deployments.
- Dashboard numbers are placeholders until the analytics phase.
