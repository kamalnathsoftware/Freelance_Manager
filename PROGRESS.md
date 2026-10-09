# Progress

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: monorepo, Docker, CI, auth, settings, design system, app shells, API client | ✅ Done |
| 2 | Platform hub, profiles, gigs, AI rewrite | ✅ Done |
| 3 | Jobs, proposals, pipeline, browser extension, email ingestion | ✅ Done |
| 4 | Unified inbox, real-time, CRM | ✅ Done |
| 5 | Notifications (in-app, push, email, WhatsApp, …) | ✅ Done |
| 6 | Orders, projects, time, invoices, finance | ✅ Done |
| 7 | Forms builder, automation rules, AI assistant | ⏳ Next |
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

## Not yet done / known gaps from Phase 1
- Team members/VA roles: table exists, no invite/permission endpoints yet.
- Web push, Storybook, Playwright smoke tests, WebSocket channel: planned for later phases.
- Web stores tokens in localStorage; a cookie-based BFF is recommended before production.
- Rate limiter is in-process; move to Redis for multi-replica deployments.
- Dashboard numbers are placeholders until the analytics phase.
