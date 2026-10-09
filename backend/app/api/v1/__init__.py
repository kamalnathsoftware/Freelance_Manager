from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    calendar,
    clients,
    finance,
    gigs,
    inbox,
    ingest,
    jobs,
    notifications,
    orders,
    platforms,
    profiles,
    projects,
    proposals,
    search,
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
