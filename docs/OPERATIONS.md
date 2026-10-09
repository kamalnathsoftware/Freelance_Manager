# Operations

## Health & monitoring
- `GET /health` → `{status, db}` (use for load-balancer / uptime checks).
- Logs are single-line JSON on stdout (`ts, level, logger, msg`) — ship with your platform’s log driver.
- Errors: set `SENTRY_DSN` and `pip install sentry-sdk`; the API initialises Sentry on start. Add the same to workers if desired.
- **Background-job dashboard:** web `/ops` (or `GET /api/v1/ops/overview`), visible to emails listed in `ADMIN_EMAILS`. Shows DB status, Celery workers online, pending deliveries, 24h counts of notification deliveries / automation runs / syncs and the latest failures (metadata only — no message content).

## Processes
| Process | Command | Notes |
|---|---|---|
| api | `uvicorn app.main:app` (container runs `alembic upgrade head` first) | scale horizontally only after moving the WebSocket hub and rate limiter to Redis (both are in-process today) |
| worker | `celery -A app.workers.celery_app.celery_app worker` | executes account syncs |
| beat | `celery -A app.workers.celery_app.celery_app beat` | **run exactly one**. Schedules: platform sync (15 min), notification delivery/retry (1 min), digests (hourly), reminders & deadlines (5 min), automation stale scans (10 min) |

## Backups
- **Postgres:** nightly `pg_dump -Fc` to off-site storage + WAL archiving/PITR if your host supports it (managed Postgres usually does). Test a restore monthly.
  `docker compose exec -T postgres pg_dump -U fm -Fc fm > backup-$(date +%F).dump`
- **Uploads volume** (`UPLOAD_DIR`): snapshot/rsync with the DB dump — DB rows reference files on disk.
- **Secrets:** keep `SECRET_KEY` and especially `ENCRYPTION_KEY` in a password manager. **Losing `ENCRYPTION_KEY` makes stored platform tokens, TOTP secrets and contact details unrecoverable** (users would have to reconnect). Rotating it requires re-encrypting those columns.

## Upgrades
`git pull && docker compose -f docker-compose.prod.yml up -d --build` — migrations run automatically. Every migration is reversible (`alembic downgrade -1`) and CI runs up → down → up on Postgres.

## Data requests
- Export: user clicks *Settings → Export my data* (`GET /api/v1/me/export`, excludes credential secrets).
- Erasure: `DELETE /api/v1/me` removes the account, all rows (FK cascades; verified by test) and uploaded files.
- Audit log retention: unbounded today — add a cleanup job if your policy requires it.

## Security checklist before going live
1. Strong `SECRET_KEY`, set `ENCRYPTION_KEY` (don’t rely on the dev fallback), `ENVIRONMENT=production`.
2. `CORS_ORIGINS` = your web origin only. HTTPS everywhere (Caddy does this).
3. Set `WHATSAPP_APP_SECRET` / `TELEGRAM_WEBHOOK_SECRET` (webhooks refuse unsigned requests with 503/403).
4. Restrict `/ops` with `ADMIN_EMAILS`.
5. Consider moving web tokens to httpOnly cookies behind a BFF (tokens are in localStorage today) and enabling CSP headers on the web app.
