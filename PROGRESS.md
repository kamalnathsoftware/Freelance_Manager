# Progress

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: monorepo, Docker, CI, auth, settings, design system, app shells, API client | ✅ Done |
| 2 | Platform hub, profiles, gigs, AI rewrite | ✅ Done |
| 3 | Jobs, proposals, pipeline, browser extension, email ingestion | ✅ Done |
| 4 | Unified inbox, real-time, CRM | ✅ Done |
| 5 | Notifications (in-app, push, email, WhatsApp, …) | ✅ Done |
| 6 | Orders, projects, time, invoices, finance | ✅ Done |
| 7 | Forms builder, automation rules, AI assistant | ✅ Done |
| 8 | Analytics, goals, team roles, GDPR, ops, seed, e2e/a11y, docs | ✅ Done |

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

## Phase 4 — what exists

**Backend** (58 tests, ~96% coverage): every inbound platform message (parsed email, extension capture, manual paste, chat widget) becomes a `Conversation`/`Message` with an auto-resolved `Client` identity. Threads: unread counts per platform, labels, star, snooze (auto-reopen when due or on a new message), archive, assign (self or team member), search (including message bodies). Replies: sent through the API only where an adapter supports it (direct clients today); otherwise stored `pending_manual` with a "reply on platform" deep link until the user confirms — idempotent via `idempotency_key`. **Response-time tracking** per platform and **SLA alerts** ("client waiting 20 min", VIPs first, threshold in user settings). AI suggest-reply / summary / translate / tone-check — all labelled; sending an AI draft needs `approved=true`. Quick replies. CRM: clients with merged platform identities, tags, VIP, notes, LTV, repeat-client flag, merge, history, create-from-job. Global search endpoint. WebSocket `/api/v1/ws?token=` (ready/ping/message.new/conversation.updated). Embeddable chat widget for the user's own site (per-visitor secret token, CORS open only on `/public/*`, no cookies). Alembic `0004` (batch mode so it also runs on SQLite).
**Web**: two-pane Inbox (filters, unread badges in the sidebar, live updates + toasts, assisted-send flow, AI draft badge, SLA banner), Clients (VIP, merge), command palette now searches clients/messages/jobs/gigs. `public/widget.js` embed script.
**Mobile**: Inbox tab with swipe snooze/archive, pull-to-refresh, offline cache + "offline" banner, conversation screen, replies queued offline and flushed with idempotency keys.

**Limitations**: WebSocket hub is in-process (needs a Redis bridge for >1 API replica); the chat widget polls every 5 s; attachments are stored as URLs (no upload/storage service yet — needs S3/R2 in a later phase); translation/tone/summary need `ANTHROPIC_API_KEY`; migrations are verified on SQLite only (Postgres run recommended in CI); team-member invites/permissions are still not implemented (assignee check already honours `TeamMember`).

## Phase 5 — what exists

**Engine** (`services/notifications.py`, 80 backend tests total): 15 event types x 6 channels (in-app, push, email, WhatsApp, SMS, Telegram) preference matrix with per-cell instant/hourly/daily mode; quiet hours in the user's timezone; **urgent items (VIP clients, SLA breaches) bypass quiet hours and digests**; de-duplication by key; queued delivery with exponential backoff (2/4/8 min, 4 attempts); **per-channel fallback** (WhatsApp/SMS/Telegram/push -> email, configurable); delivery log with manual retry; digest flush (hourly, or daily at the user's digest hour); Celery beat jobs for due deliveries (1 min), digests (hourly) and reminders (5 min: proposal follow-ups, SLA breaches). Triggered from: inbound messages, parsed platform events (orders, offers, revisions, payments, reviews, bid viewed/accepted/declined, job matches), sync failures, low credits.
**Channels**: SMTP email; Expo push (-> FCM/APNs) and Web Push (VAPID, needs optional `pywebpush`); WhatsApp Cloud API (approved template with title/body/reply-code params); Twilio SMS; Telegram bot with `/start <code>` linking. WhatsApp/SMS are **never sent without a number and explicit opt-in**; WhatsApp `STOP`/`START` toggle opt-in.
**Webhooks**: WhatsApp verify (GET) + inbound (POST, HMAC-SHA256 signature mandatory; 503 if unconfigured) — replies are routed to the right thread via WhatsApp reply-context or a leading short code (`A7F2 thanks!`); failed-status receipts trigger fallback. Because most platforms have no messaging API, a routed reply is saved as `pending_manual` and the user is told to paste it on the platform. Telegram webhook (secret-header verified).
**Web**: bell dropdown with unread badge (live via WebSocket), Notifications page (all + delivery log with retry), Settings: channel setup/opt-in/test sends, quiet hours, full preference matrix, browser-push enable + service worker. **Mobile**: Expo push registration on launch, tap deep-links into the thread.

**Not verified against live providers**: WhatsApp/Twilio/Telegram/Expo/Web Push calls are tested with mocked HTTP only. WhatsApp needs a Meta-approved template named `fm_notification` (3 body params) before business-initiated sends work. The `deadline` event type exists but is emitted starting in Phase 6.

## Phase 6 — what exists

**Backend** (100 tests total): Orders (manual, from a won proposal, or **auto-created/updated from parsed platform emails**: new order, delivered/completed, revision, payment), status lifecycle with revision-limit warning, milestones (pay once; completion records only the unpaid remainder — no double counting), delivery checklist, file links, order->project. Projects with a todo/doing/done task board; **time tracking** (one running timer, manual entries, summary, CSV timesheet). Invoices (per-user numbering `INV-YYYY-0001`, tax, multi-currency, draft->sent->paid/void, **PDF**, bill unbilled time which locks entries and releases them on void). Expenses, payments (gross/fee/net — fee schedule per platform with user overrides), **platform-fee calculator**, earnings reports by month/platform/client with base-currency conversion from the user's manual FX table (unknown rates are flagged, not hidden), CSV export, flat-rate **tax estimate with an explicit not-tax-advice disclaimer**, monthly goal progress. Calendar: aggregated agenda (order/milestone/task/invoice deadlines, follow-ups, custom events), `.ics` download, secret-URL subscription feed (rotatable), **Google Calendar two-way sync** to a dedicated calendar (pull wins by `updated`, deadlines pushed one-way) with OAuth token refresh (also now used by Gmail polling, fixing the earlier no-refresh gap). Reminder job now emits `deadline` notifications (due within 24h, overdue invoices). Payment recorded -> `payment_received` notification. Migration `0006`.
**Web**: Orders (status, checklist, milestones, project link), Projects (task board, live timer, timesheet export, invoice unbilled time), Finance (overview chart/KPIs/goal, invoices with PDF, expenses, payments, fee calculator), Calendar (agenda, add event, .ics, subscription URL, Google connect/sync). **Mobile**: Projects tab with start/stop timer.

**Caveats**: default platform fee schedules are approximations — verify/override; FX is manual (no live rates); Google Calendar sync is tested against mocked HTTP only; invoices are not emailed to clients yet (PDF download + mark sent); the PDF uses core Latin-1 fonts (non-Latin characters are replaced).

## Phase 7 — what exists

**Forms** (127 backend tests total, 96% coverage): schema builder with 11 field types, validation of keys/types/options, **conditional logic** (`show_if`, evaluated server-side — hidden answers are dropped and never required), versioning on edit, 5 built-in templates (project brief, revision request, client onboarding, review request, NDA). **Public forms** at `/f/<key>` (embeddable via iframe): server-side validation, honeypot, per-IP rate limit, CORS only on `/public/*`, file upload with type/size limits (local-disk store behind `services/storage.py`; owner-only download with `nosniff`). Submissions land in CRM (client by email) + inbox (conversation) + notification, and can **auto-create a project and/or a job + proposal draft**; CSV export neutralises spreadsheet-formula injection. **E-signature / NDA**: typed-name + explicit agreement tick, stores timestamp, IP, user agent and a SHA-256 of the agreement text+version; downloadable PDF certificate (a *simple* electronic signature — legal sufficiency varies by jurisdiction).
**Automation engine**: 8 triggers (job created, message received, conversation stale, proposal stage changed / stale, order status changed, payment received, form submitted), AND-conditions with 9 operators, 7 actions (notify with channel override, draft proposal from template or AI, create task, send form link, label, star, set follow-up). Safety: no webhook/outbound-HTTP action (SSRF), actions never fire further triggers (no loops), 50 runs/hour/rule, per-event de-duplication, every run logged, **dry-run test endpoint**, drafts are never auto-approved and client-facing sends on non-API platforms are queued as `pending_manual`. Ships 4 presets mirroring the product brief examples. Celery beat scans for stale conversations/proposals every 10 min.
**AI assistant**: deterministic daily briefing (unread, clients waiting, deadlines, new matches, follow-ups, overdue invoices) with optional Claude narrative; requirement extraction from text/thread/form submission (JSON-parsed, with a parse-failure fallback); pricing advice combining the bid heuristic with the user's own win rate by price band; grounded chat. Everything AI is labelled `ai_generated`/`requires_approval`. Migration `0007`.
**Web**: Forms builder (add/reorder fields, options, conditions, signature settings, auto-actions, publish, link/embed copy, submissions view, CSV, certificate PDF), public form renderer, Automations (presets, rule editor, dry-run tester, run log), Assistant slide-over (briefing, extract, chat).

**Caveats**: file storage is local disk (use S3/R2 in production); the rule editor takes action parameters as JSON; automation `send_form` needs an existing conversation with the client; AI features need `ANTHROPIC_API_KEY`.

## Phase 8 — what exists

**Team & workspaces:** invite a VA by email (signed 7-day link, must sign in with that address), roles `full` / `messaging_only` / `view_only`, `X-Workspace` header + workspace switcher in the web top bar. One permission matrix (`api/deps.member_allowed`) — account, security, credentials, API keys, Gmail/Calendar OAuth, contact details and team management are blocked for every member. Role changes/removal apply immediately; every member write lands in the owner's audit log; WebSocket supports `?workspace=`.
**Analytics & goals:** `/analytics/overview` (earnings by day/week/month with period-over-period change, by platform, top clients, proposal funnel, win rate by platform/template/price band/hour, response times, utilization vs weekly capacity, upcoming deadlines), `/goals` (monthly/yearly income + weekly hours, pace status, forecast = run-rate / + committed orders net of fees / + stage-weighted pipeline with stated assumptions), branded one-page **PDF report**, CSV export. Dashboard now uses real data (charts lazy-loaded: dashboard first-load JS 243 kB → 166 kB).
**GDPR:** full export (30+ tables, no credential secrets, decrypted contact details) and erasure that removes every row (FK cascades verified by a test that checks all `user_id` tables) and uploaded files.
**Ops:** `/ops` job dashboard (admin emails only), gzip, structured logs, Sentry hook, Celery beat for all schedules; `docs/OPERATIONS.md` (backups, restore, key custody, upgrade, security checklist); production compose + Caddy (auto-HTTPS).
**Seed data:** `python -m app.seed` builds a coherent demo workspace (6 months of payments, pipeline in every stage, conversations, orders with milestones, time entries, invoices, forms with submissions, automations…). A test asserts every list screen is non-empty.
**Quality:** Playwright e2e (11 flows) + **axe WCAG 2.0/2.1 A/AA scans of 20+ pages in light and dark** — fixed real issues (muted/brand/danger/success text contrast with separate text tokens, tablist semantics, link-in-text, chart tooltip contrast). i18n (EN/ES, parity test), `/design-system` living style guide (Storybook equivalent), mobile Jest tests, CI jobs for backend, Postgres migrations, web, mobile, e2e.

---

# Final summary

## Verified in this environment
| Area | Evidence |
|---|---|
| Backend | 149 pytest tests, **96% coverage**, ruff + mypy clean, FK cascades enforced, tenant-isolation tests per module |
| Migrations | 7 revisions; up/down/`alembic check` on SQLite locally. **Postgres run is in CI** (`migrations-postgres` job) — I could not run Postgres/Docker here |
| Web | typecheck, ESLint, 8 Vitest tests, production build, **19 Playwright tests** (flows + axe in both themes) against the real API |
| Mobile | typecheck + 4 Jest tests. **Never run on a device/simulator** |
| Extension | manifest/JS syntax-checked; not loaded in Chrome here |
| Compose | both compose files parse (`docker compose config`); **images were never built or started** (no Docker daemon here) |

## Built, but only tested against mocks (needs your credentials/accounts to prove live)
Gmail polling & OAuth, Google Calendar sync, WhatsApp Cloud API / Twilio / Telegram / Expo / Web Push sending and webhooks, Claude API features, Freelancer.com profile sync.

## Stubbed pending access
- **Upwork API** (profile sync, job feed, proposal submit): adapter is wired and degrades to the assisted flow; needs Upwork-approved API keys and implementing the GraphQL calls.
- Job feeds (`fetch_jobs`) for Upwork/Freelancer — jobs currently arrive via email, extension, manual entry and forms.

## Known limitations / honest caveats
- Email-parsing patterns are heuristic: tune with your real notification emails.
- WebSocket hub and rate limiter are in-process (single API replica) — bridge to Redis before scaling out.
- Web stores tokens in `localStorage`; a cookie-based BFF + CSP is recommended before public launch.
- File storage is local disk; move to S3/R2 for multi-node.
- Platform fee schedules and per-platform field limits are defaults to verify; FX rates are manual; the tax estimate is a flat-rate aid, not advice; the proposal funnel is approximate (no stage history).
- Invoices aren't emailed to clients yet (PDF + mark sent); PDF uses Latin-1 core fonts.
- Mobile: no widgets, no deep-link tests, limited screens (Home, Inbox + thread, Projects/timer, More).
- Chrome extension uses generic page parsing and has no icons.
- No load/performance testing beyond bundle-size work; no Storybook proper (see design-system page).

## Recommended next steps
1. Add real credentials in a staging environment and walk through Gmail, WhatsApp (template approval takes days), Calendar, push — then add fixtures from real emails to the parser tests.
2. Apply for Upwork API access; implement the GraphQL profile/jobs/proposals calls behind the existing capability flags.
3. Run the stack on a staging VPS with `docker-compose.prod.yml`; verify backups/restore using `docs/OPERATIONS.md`.
4. Redis-backed WebSocket hub + rate limiter, S3 storage, cookie-based web auth, email delivery of invoices, stage-history table for exact funnels.
5. Mobile polish (more screens, EAS builds, push credentials) and a Chrome Web Store package for the extension.
6. Pen-test / security review before onboarding other people's data.
