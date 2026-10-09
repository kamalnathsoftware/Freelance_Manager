# Freelance Manager

One app (web + mobile + API) to manage every freelance platform — Fiverr, Upwork, Freelancer.com, PeoplePerHour, Toptal, Guru, LinkedIn Services, Contra and direct clients — from one place.

> Status: **Phase 1 (Foundation)** complete. See [PROGRESS.md](PROGRESS.md) for the roadmap.

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI, SQLAlchemy 2 (async), Alembic, Celery, JWT auth |
| `web/` | Next.js 14 (App Router), Tailwind, TanStack Query, PWA manifest |
| `mobile/` | Expo / React Native, Expo Router, NativeWind, SecureStore + biometric unlock |
| `packages/shared/` | Typed API client (refresh rotation), Zod schemas, design tokens |

## Quick start (Docker)

```bash
cp .env.example .env      # set SECRET_KEY and ENCRYPTION_KEY
docker compose up --build
```

- Web http://localhost:3000 · API docs http://localhost:8000/api/docs · Mailhog http://localhost:8025

## Local development

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
ruff check . && mypy app && pytest --cov=app          # tests use in-memory SQLite
DATABASE_URL=... alembic upgrade head && uvicorn app.main:app --reload

# web + shared
npm install && npm run web
npm run typecheck && npm test && npm run build

# mobile
npm -w mobile run start
```

Generate typed API schema: `python scripts/export_openapi.py && npm -w @fm/shared run generate`.

## Architecture

```
 Web (Next.js) ─┐                 ┌─ Postgres
 Mobile (Expo) ─┼─ /api/v1 REST ─▶ FastAPI ─┼─ Redis ◀─ Celery worker + beat
 Extension ─────┘  + WebSocket    └─ platform adapters (API / email / manual)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

## Compliance

Most freelance platforms (notably Fiverr) expose **no public API** for gigs, bids or messages, and their Terms of Service forbid scraping, automated login and auto-bidding. This project therefore:

1. uses **official APIs/OAuth** only where they exist (Upwork, Freelancer.com),
2. ingests **notification emails** from the user's own mailbox via OAuth,
3. offers **assisted/manual** tools (deep links, copy-to-clipboard, a user-driven browser extension).

It never automates logins, bypasses CAPTCHAs, scrapes, or submits bids without explicit user approval. Every AI-generated message is labelled and requires approval before sending.
