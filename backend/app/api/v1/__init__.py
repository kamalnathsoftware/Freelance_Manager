from fastapi import APIRouter

from app.api.v1 import (
    ai,
    analytics,
    assistant,
    auth,
    automations,
    calendar,
    clients,
    finance,
    forms,
    gigs,
    inbox,
    ingest,
    jobs,
    notifications,
    ops,
    orders,
    platforms,
    profiles,
    projects,
    proposals,
    search,
    team,
    users,
    webhooks,
    widget,
    ws,
)

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(platforms.router)
router.include_router(profiles.router)
router.include_router(gigs.router)
router.include_router(ai.router)
router.include_router(jobs.router)
router.include_router(proposals.router)
router.include_router(ingest.router)
router.include_router(inbox.router)
router.include_router(clients.router)
router.include_router(search.router)
router.include_router(widget.router)
router.include_router(ws.router)
router.include_router(notifications.router)
router.include_router(webhooks.router)
router.include_router(orders.router)
router.include_router(projects.router)
router.include_router(finance.router)
router.include_router(calendar.router)
router.include_router(forms.router)
router.include_router(automations.router)
router.include_router(assistant.router)
router.include_router(team.router)
router.include_router(analytics.router)
router.include_router(ops.router)
