# Architecture

## Components
- **API** (`backend/app`): `api/v1` routers → `services` (business logic) → `models` (SQLAlchemy). Cross-cutting: `core/{config,security,crypto,errors,ratelimit,db}`.
- **Workers**: Celery app in `app/workers`; beat will schedule per-platform syncs (phase 2).
- **Clients**: web and mobile share `@fm/shared` (`ApiClient`, validation, tokens).

## Auth flow
1. `POST /auth/login` → tokens, or `{mfa_required, mfa_token}` when TOTP is on → `POST /auth/login/2fa`.
2. Access token (15 min) carries `sid`; each request checks the session isn't revoked.
3. `POST /auth/refresh` rotates the refresh token; replaying an old one revokes the session.

## Planned adapter layer (phase 2)
`PlatformAdapter` with `capabilities()`; tiers: official API/OAuth → email ingestion → assisted/manual. The UI renders only actions a platform's capability set allows.

## Error format
`{"error": {"code": "...", "message": "...", "details": ...}}` for all non-2xx responses.
