# Freelance Manager

One app — **web, mobile and API** — to run every freelance platform from one place: Fiverr, Upwork, Freelancer.com, PeoplePerHour, Toptal, Guru, LinkedIn Services, Contra and your own direct clients.

Profiles · gigs · job inbox & match scoring · proposals & pipeline · unified inbox · CRM · orders · projects & time · invoices & finance · calendar · forms & e-signature · automations · AI assistant · multi-channel notifications · analytics & goals.

> **Honest about integrations.** Most platforms (notably Fiverr) have no public API for gigs, bids or messages, and their Terms of Service forbid scraping, automated login and auto-bidding. This app is built around that reality — see [Compliance](#compliance) and [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) for exactly what works per platform.

## Quick start (one command)

```bash
cp .env.example .env            # set SECRET_KEY and ENCRYPTION_KEY (see comments inside)
docker compose up --build
docker compose exec api python -m app.seed    # optional: realistic demo workspace
```

| What | Where |
|---|---|
| Web app | http://localhost:3000 — demo login `demo@freelancemanager.dev` / `demo1234!` (after seeding) |
| API docs (OpenAPI) | http://localhost:8000/api/docs |
| Test mailbox (verification / reset / invite emails) | http://localhost:8025 |

## Local development

**Prerequisites:** Python 3.11+, Node 22+, (optional) Docker.

**Windows (PowerShell) — no Docker, SQLite:**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -e ".[dev]"
$env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
$env:SECRET_KEY = "dev-secret-key-change-me-0123456789"
$env:CORS_ORIGINS = '["http://localhost:3000"]'
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```
```powershell
# second terminal, from the repo root
npm install
cd web
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
npm run dev
```
(`&&` and `export` are bash-only; in PowerShell use `;` and `$env:NAME = "value"`.)

**macOS / Linux:**

```bash
# backend (Python 3.12+)
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest --cov=app                  # 149 tests on in-memory SQLite, FK cascades enforced
ruff check . && ruff format --check . && mypy app
DATABASE_URL=postgresql+asyncpg://fm:fm@localhost:5432/fm alembic upgrade head
python -m app.seed && uvicorn app.main:app --reload

# web + shared client (Node 22)
npm install
npm run web                       # http://localhost:3000
npm run typecheck && npm test && npm run build
cd web && npx playwright install chromium && npx playwright test   # 19 e2e + WCAG AA scans (starts API+web itself)

# mobile (Expo)
npm -w mobile run start           # scan with Expo Go; set EXPO_PUBLIC_API_URL to your machine's LAN address
npm -w mobile test

# regenerate typed API schema
python scripts/export_openapi.py && npm -w @fm/shared run generate
```

## Architecture

```
                  ┌──────────── Web (Next.js 14, PWA) ───────────┐
 Chrome extension │  Mobile (Expo / React Native)                │  Embedded chat widget
 (user-clicked    │  ── @fm/shared: typed ApiClient (token       │  Public forms /f/<key>
  page capture)   │     refresh, workspaces), Zod, tokens ──     │  (anonymous visitors)
        │         └───────────────┬──────────────────────────────┘          │
        └──────────────► REST /api/v1 + WebSocket /api/v1/ws ◄──────────────┘
                                  │
                         FastAPI (async SQLAlchemy 2)
        ┌───────────┬─────────────┼───────────────┬───────────────────┐
   services/        │        adapters/            │             notify/channels
   (business rules) │   PlatformAdapter per site  │   email · push (Expo/Web) · WhatsApp
   automation engine│   capability matrix:        │   SMS · Telegram  (+ webhooks in)
   inbox · finance  │   API → email → manual      │
        └───────────┴──────┬──────┴───────────────┴───────────────────┘
                  PostgreSQL        Redis ── Celery worker + beat
                                   (platform sync, deliveries & retries, digests,
                                    reminders, automation scans)
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · decisions: [docs/DECISIONS.md](docs/DECISIONS.md) · operations: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Connecting each platform

Open **Platforms → Add account**, then:

| Platform | Mode | How to connect |
|---|---|---|
| **Upwork** | Official API (GraphQL/OAuth) | Needs API keys approved by Upwork. Paste the OAuth token on the account card. *Sync is stubbed until approved keys exist* — the code path is in place and logs "skipped" otherwise. |
| **Freelancer.com** | Official API (OAuth2) | Create an app at developers.freelancer.com, paste the token. Profile sync is implemented. |
| **Fiverr, PeoplePerHour, Toptal, Guru, LinkedIn, Contra** | Email + assisted | No API. **Settings → connect Gmail** (read-only scope) or forward platform notification emails; install the Chrome extension for job posts/messages you are viewing; use copy-ready gig/proposal exports and “reply on platform” deep links. |
| **Direct clients** | Native | Chat widget, forms, invoices — everything works without a platform. |

**Gmail / Google Calendar:** create an OAuth client in Google Cloud, set `GOOGLE_CLIENT_ID/SECRET`, and add redirect URIs `<WEB_BASE_URL>/settings/gmail/callback` and `<WEB_BASE_URL>/calendar/google/callback`.

**Chrome extension:** `chrome://extensions` → Developer mode → *Load unpacked* → `extension/`. Create an API key under **Settings → API keys** and paste it in the extension settings.

## Notification channels

- **Email:** set `SMTP_*`.
- **Push:** mobile uses Expo push (FCM/APNs) automatically; for browser push generate VAPID keys (`npx web-push generate-vapid-keys`), set `VAPID_*`, `pip install pywebpush`.
- **WhatsApp (Meta Cloud API):** create a Meta app + WhatsApp Business number, then
  1. set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`;
  2. create and get approved a message template named `fm_notification` (or set `WHATSAPP_TEMPLATE`) with **three body parameters**: `{{1}}` title, `{{2}}` text, `{{3}}` reply code;
  3. configure the webhook URL `https://<API_DOMAIN>/api/v1/webhooks/whatsapp` with your verify token, subscribe to *messages*;
  4. in **Settings → Notifications** add your number and tick the opt-in box. Replying `STOP`/`START` toggles opt-in; replying to a notification (or starting with its 4-character code) routes your answer to the right inbox thread.
- **SMS:** `TWILIO_*`. **Telegram:** create a bot, set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, point `setWebhook` at `/api/v1/webhooks/telegram`, then “Get link code” in settings.
- Every channel has instant / hourly / daily modes, quiet hours, retry with backoff and an automatic fallback channel (e.g. WhatsApp fails → email). VIP clients and SLA breaches bypass quiet hours.

## AI features

Set `ANTHROPIC_API_KEY` (and optionally `AI_MODEL`). Used for profile/gig rewrites, proposal and reply drafts, thread summaries, requirement extraction, translation, tone check and the assistant. **All AI output is labelled and needs your approval — nothing is auto-sent or auto-submitted.** Without a key, those endpoints return 503 and everything else works.

## Deployment

Any VPS with Docker works (Hetzner, DigitalOcean, Fly machines, a home server…):

```bash
git clone … && cd Freelance_Manager
cp .env.example .env     # set SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD, APP_DOMAIN, API_DOMAIN, ADMIN_EMAILS, provider keys
# DNS: A records for APP_DOMAIN and API_DOMAIN → this server
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
docker compose -f docker-compose.prod.yml exec api python -m app.seed --email you@example.com --password '…'   # optional demo data
```

Caddy terminates TLS (Let’s Encrypt), the API container runs `alembic upgrade head` on start. Back up the `pgdata` and `uploads` volumes (see [docs/OPERATIONS.md](docs/OPERATIONS.md)). Managed alternatives: Render/Railway/Fly for API + worker + beat, Neon/Supabase/RDS for Postgres, Upstash for Redis, Vercel for `web/` (set `NEXT_PUBLIC_API_URL`).

## Security & privacy

bcrypt password hashing, 15-minute access tokens + rotating refresh tokens with reuse detection, per-device sessions you can revoke, optional TOTP 2FA, platform tokens / TOTP secrets / contact details encrypted with Fernet (`ENCRYPTION_KEY`), API keys stored as hashes, signature-verified webhooks, rate limiting, CORS allow-list, input validation everywhere, an audit log (including everything a team member does in your workspace), tenant isolation tests, GDPR-style full **data export** and **account erasure** (rows + uploaded files). Team members get `full`, `messaging_only` or `view_only` roles and can never touch account, credentials, API keys or team settings.

## Compliance

This project deliberately **does not**: log in to platforms on your behalf, scrape, bypass CAPTCHAs, run headless browsers against platforms, or submit bids/messages automatically where a platform forbids it. Instead it uses **(1)** official APIs/OAuth where they exist, **(2)** the user’s own notification emails read via read-only OAuth (or forwarded), and **(3)** assisted tools — deep links, copy-ready text, and a Chrome extension that only reads the page you are looking at when you click it. Every proposal needs an explicit approval step enforced on the server, and automations can draft and notify but never submit. You are responsible for following each platform’s terms.

## Repository layout

```
backend/     FastAPI app (app/api/v1 routers, services, adapters, notify, models), Alembic, Celery, tests
web/         Next.js app + public form/chat pages, Playwright e2e + axe accessibility tests
mobile/      Expo app (inbox with offline queue, projects/timer, push), Jest tests
packages/shared/  typed API client, Zod schemas, design tokens
extension/   Chrome MV3 capture extension
docs/        architecture, decisions, integrations matrix, operations
```

Status and roadmap: [PROGRESS.md](PROGRESS.md).
