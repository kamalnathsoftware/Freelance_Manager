# Decisions

- **Stack** follows the brief: FastAPI + SQLAlchemy 2 async + Alembic + Postgres/Redis/Celery; Next.js App Router; Expo.
- **Celery** (not ARQ) for workers/beat — more mature scheduling.
- **Tests use in-memory SQLite** (aiosqlite) for speed; models avoid Postgres-only types. Run integration tests against Postgres in CI later.
- **Tailwind v3 + hand-rolled shadcn-style components** instead of the shadcn CLI, to keep the scaffold reproducible/offline.
- **Monorepo via npm workspaces** (web, mobile, packages/shared). Mobile imports shared source directly via Metro `watchFolders`.
- **Refresh tokens**: opaque random strings, stored hashed; one `AuthSession` per device; the previous hash is retained so replay of a rotated token revokes the session (theft detection).
- **Access tokens**: 15-minute HS256 JWT referencing the session id, so revoking a session takes effect immediately.
- **Vault**: Fernet; `ENCRYPTION_KEY` required in production, dev derives a key from `SECRET_KEY`.
- **Password hashing**: bcrypt (input truncated at 72 bytes).
- **Email verification does not gate login** (only flagged); gate sensitive actions later.
- **API client generation**: `scripts/export_openapi.py` + `openapi-typescript`; until wired into CI the shared types are hand-maintained.
- **Single-owner tenancy for now**: all data keyed by `user_id`; `TeamMember` will scope access in a later phase.

## Added during phases 2-8
- **Capability sets, not feature flags per platform in the UI.** Adapters declare what really works; Fiverr deliberately lacks `send_message`/`submit_proposal`.
- **Human approval is enforced in the API, not just the UI.** `submit`, `mark-submitted` and the `submitted` stage move return 409 without a prior `approve`; editing a proposal revokes approval; AI replies need `approved=true`.
- **Assisted delivery state:** outbound messages on platforms without an API are stored `pending_manual` and only count as replied (and stop the SLA clock) when the user confirms.
- **Email ingestion over scraping.** Gmail read-only OAuth reads metadata + snippet only; unknown senders/subjects are ignored and never stored.
- **Notifications:** WhatsApp/SMS require an explicit opt-in flag before any send; defaults keep paid/noisy channels off; urgent (VIP, SLA) items bypass quiet hours and digests.
- **Automations cannot call arbitrary URLs** (SSRF) and cannot trigger further automations (loops); the engine rate-limits itself.
- **Money:** payments table is the source of truth; FX is a manual table (no hidden live-rate dependency, unknown rates are reported); fee schedules are defaults the user can override; tax estimate is a flat-rate helper with a disclaimer.
- **Team roles via `X-Workspace` header** rather than separate tenants/subdomains: one code path, enforced by a single permission matrix + audit log.
- **Files on local disk** behind `services/storage.py` (swap for S3/R2); type allow-list, size limit, random on-disk names, owner-only authenticated download with `nosniff`.
- **Tests run on SQLite with `PRAGMA foreign_keys=ON`** so cascade deletes behave like Postgres; CI additionally runs the migrations (up/down/up, `alembic check`, seed) on Postgres.
- **Storybook equivalent:** a public `/design-system` page renders every core component/state in light and dark and is covered by the axe scan — lighter than Storybook, same purpose.
- **Accessibility:** accent colours have separate fill and text tokens (`bg-brand` vs `text-brand`) so both modes meet WCAG AA; enforced by Playwright + axe on 20+ pages in both themes.
- **Analytics funnel is approximate** because stage history isn't stored (documented in the API and UI). Forecast probabilities come from the user's own closed proposals once there are ≥5, otherwise stated defaults.
