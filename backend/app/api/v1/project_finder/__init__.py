"""Project Finder: lead sources, job feed, outreach CRM, templates, proposals, stats, foreign-client helper."""

from fastapi import APIRouter

from app.api.v1.project_finder import (
    foreign,
    jobs,
    leads,
    outreach,
    proposals,
    settings,
    sources,
    stats,
    templates,
)

router = APIRouter(prefix="/project-finder")
router.include_router(settings.router)
router.include_router(leads.router)
router.include_router(outreach.router)
router.include_router(templates.router)
router.include_router(sources.router)
router.include_router(jobs.router)
router.include_router(proposals.router)
router.include_router(stats.router)
router.include_router(foreign.router)
