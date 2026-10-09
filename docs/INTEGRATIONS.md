# Integrations (capability matrix — target state)

| Platform | Tier | Profile | Gigs | Jobs | Messages | Send bid | Orders |
|---|---|---|---|---|---|---|---|
| Upwork | API (GraphQL/OAuth) | read/update | – | read | read/send | via API w/ approval | read |
| Freelancer.com | API (OAuth) | read | – | read | read/send | via API w/ approval | read |
| Fiverr | Email + manual | manual | manual | email | email → deep link | n/a | email |
| PeoplePerHour | Email + manual | manual | manual | email | email → deep link | manual | email |
| Toptal / Guru / LinkedIn / Contra | Email + manual | manual | manual | email/extension | email → deep link | manual | email |
| Direct clients | Native | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Nothing is implemented yet beyond the account/auth foundation (Phase 1). API access to Upwork/Freelancer requires approved developer credentials; adapters will be stubbed behind capability flags until those are available.
