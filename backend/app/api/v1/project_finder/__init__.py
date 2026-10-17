"""Project Finder: lead sources, job feed, outreach CRM, templates, proposals, stats, foreign-client helper."""

from fastapi import APIRouter

from app.api.v1.project_finder import leads, outreach, settings, templates

router = APIRouter(prefix="/project-finder")
router.include_router(settings.router)
router.include_router(leads.router)
router.include_router(outreach.router)
router.include_router(templates.router)
