# Integrations — capability matrix (what actually works)

Legend: ✅ implemented · 🟡 implemented, needs your credentials/approval, untested against the live service · ✋ assisted (you complete the step) · ➖ not available

| Platform | Tier | Profile | Gigs | Jobs | Messages | Bids | Orders & payments |
|---|---|---|---|---|---|---|---|
| **Upwork** | Official API (OAuth/GraphQL) | 🟡 stubbed until API keys are approved | ➖ | email ✅ · extension ✅ · API feed ➖ | email ✅ · reply ✋ | ✋ copy + open job (API submit path exists behind the adapter, disabled without keys) | email ✅ |
| **Freelancer.com** | Official API (OAuth2) | 🟡 `/users/0.1/self` sync | ➖ | email ✅ · extension ✅ | email ✅ · reply ✋ | ✋ | email ✅ |
| **Fiverr** | Email + assisted | ✋ copy-ready | ✅ master gig → copy-ready export + deep link | email ✅ · extension ✅ | email ✅ · reply ✋ | ➖ (not a bidding platform) | email ✅ |
| **PeoplePerHour** | Email + assisted | ✋ | ✋ | email ✅ · extension ✅ | email ✅ · reply ✋ | ✋ | email ✅ |
| **Toptal / Guru / Contra** | Email + assisted | ✋ | ✋ | email ✅ · extension ✅ | email ✅ · reply ✋ | ✋ | email ✅ |
| **LinkedIn Services** | Email + assisted | ✋ | ✋ | email ✅ · extension ✅ | email ✅ · reply ✋ | ➖ | email ✅ |
| **Direct clients** | Native | ✅ | ✅ | ✅ (manual, forms) | ✅ chat widget, direct send | ✅ | ✅ orders, invoices (PDF), payments |

## What “email ✅” parses
`services/email_parser.py` recognises notification emails from each platform’s domain and classifies them into: new message, order, order delivered/completed, revision request, offer, job invite, payment, review, bid viewed/accepted/declined. Counterparty names, order ids and amounts are extracted heuristically. **The patterns are conservative and based on typical subject lines — expect to tune them against your real emails** (add fixtures to `tests/test_phase3.py`).

## Other integrations
| Service | Used for | Status |
|---|---|---|
| Gmail API (`gmail.readonly`) | email ingestion (metadata + snippet only), token refresh | 🟡 mocked-HTTP tests only |
| Google Calendar API | two-way sync with a dedicated “Freelance Manager” calendar; deadlines pushed one-way | 🟡 mocked-HTTP tests only |
| Anthropic API | rewrites, drafts, summaries, extraction, assistant | 🟡 mocked in tests |
| WhatsApp Cloud API | notifications (approved template), inbound replies, opt-in/out, status receipts | 🟡 mocked + signature tests |
| Twilio SMS, Telegram Bot API | optional notification channels | 🟡 mocked |
| Expo Push (FCM/APNs), Web Push (VAPID) | push notifications | 🟡 Expo mocked; Web Push needs `pywebpush` |

## Adding a platform
1. Add rules to `adapters/rules.py` (field limits).
2. Add the adapter to `adapters/registry.py` (copy `_em(...)` for email/manual platforms; subclass `PlatformAdapter` for an API platform and declare only capabilities that really work).
3. Add the sender domain to `services/email_parser.DOMAINS` and a fee entry to `services/finance.PLATFORM_FEES`.
4. Add brand colour in `packages/shared/src/tokens.ts`.
