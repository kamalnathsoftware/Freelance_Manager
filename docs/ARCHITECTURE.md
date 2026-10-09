# Architecture

## Backend (`backend/app`)
```
api/v1/*.py      thin routers (validation + auth + response shaping)
api/deps.py      auth, workspace (team member) resolution, role permission matrix
services/*.py    business rules; routers call these, tests hit both
adapters/        PlatformAdapter ABC, per-platform adapters, capability sets, field-limit rules
notify/          channel providers (email, Expo/Web push, WhatsApp, SMS, Telegram)
models/*.py      SQLAlchemy 2 models (one module per area)
core/            config, db, security (JWT/bcrypt), crypto (Fernet), errors, rate limit, realtime hub
workers/         Celery app + beat schedule
seed.py          realistic demo data
```

### Request flow & tenancy
Every row carries `user_id` (the *workspace owner*). `current_auth` resolves the bearer token to the signed-in user; if `X-Workspace: <owner id>` is present and the user is a `TeamMember` of that owner, `Auth.user` becomes the owner (data scope) while `Auth.actor` stays the member (audit). `member_allowed(role, method, path)` is the single permission matrix — account, security, credential, API-key, Gmail/Calendar-OAuth, contact-detail and team routes are blocked for every member role. Routers fetch rows through `get_owned()` which returns 404 (never 403) for other tenants’ rows. Tenant isolation is covered by tests per module.

### Platform adapters (the integration reality)
`PlatformAdapter` exposes `connect, sync_profile, sync_gigs, fetch_jobs, fetch_messages, send_message, submit_proposal, sync_orders, capabilities()`. Each adapter declares a *capability set*; the API and UI only offer actions in that set (e.g. Fiverr has no `send_message`/`submit_proposal`). Tiers: **api** (Upwork, Freelancer.com) → **email** ingestion (parse the user’s own notification emails) → **manual/assisted** (deep links, copy-ready exports, user-clicked browser extension). Submission/sending always follows: *explicit approval → try official API if supported → otherwise return the assisted flow and wait for the user to confirm they did it*.

### Event pipeline
```
email / extension / widget / form / manual
        └─► ingest.record_event / inbox.add_inbound
                ├─► PlatformEvent + account counters
                ├─► orders.apply_platform_event (create/deliver/revise/pay orders)
                ├─► inbox: Client identity → Conversation → Message  ──► WebSocket (hub)
                ├─► notifications.emit → preference matrix → deliveries → channels (retry/fallback/digest)
                └─► automation.fire → rules → actions (notify, draft, task, label, queue reply…)
```
Side-effect failures in notifications/automations are caught and logged; they never fail the originating request.

### Notifications
`notify()` creates a `NotificationEvent` (deduped by key) and one `NotificationDelivery` per channel allowed by the user’s event×channel matrix and holding a valid destination/opt-in. Timing: urgent → now; quiet hours → deferred to the end of the window; hourly/daily → parked as `digest`. `attempt()` sends; retryable errors back off 2/4/8 min (max 4 tries); terminal failures trigger the configured fallback channel. Celery beat drives `process_due`, `flush_digests`, `scan_reminders`.

### Automation engine
`fire(user, trigger, payload, dedupe_key)` loads enabled rules for that trigger, evaluates AND-conditions (9 operators) and runs ≤8 actions. Guarantees: no outbound HTTP action, actions never fire further triggers, 50 runs/h/rule, per-event dedupe, every run logged, dry-run endpoint, drafts never auto-approved, non-API client replies queued as `pending_manual`.

### Money
Payments are the source of truth for earnings (`gross, fee, net, currency`). Fees come from a per-platform schedule (overridable per user). Reports convert to the user’s base currency with a *manual* FX table; unknown currencies are flagged in the response rather than silently converted. Orders, milestones and invoices all create `Payment` rows idempotently per `(source, source_id)`.

### Real-time
`core/realtime.Hub` is an in-process fan-out keyed by user id used by `/api/v1/ws`. Single API replica only; to scale out, publish through Redis pub/sub and subscribe per replica.

## Clients
- **Web** (Next.js App Router, Tailwind, TanStack Query): `app/(app)/*` authenticated pages inside `AppShell`; `app/f/[key]` public forms; `public/widget.js` chat embed; i18n via a small dictionary provider; charts lazy-loaded.
- **Mobile** (Expo Router, NativeWind): tabs, offline cache + reply queue (`src/offline.ts`), SecureStore tokens, biometric unlock, Expo push.
- **Shared** (`packages/shared`): `ApiClient` (single-flight refresh, workspace header, WebSocket reconnect), Zod schemas, design tokens.
- **Extension** (`extension/`): MV3, `activeTab` only, ingest-scoped API key.

## Error format
All non-2xx responses: `{"error": {"code": "...", "message": "...", "details": ...}}`.
