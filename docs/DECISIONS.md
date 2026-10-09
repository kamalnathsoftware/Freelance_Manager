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
