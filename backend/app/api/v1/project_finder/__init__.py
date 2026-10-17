"""Project Finder: lead sources, job feed, outreach CRM, templates, proposals, stats, foreign-client helper."""

from fastapi import APIRouter

from app.api.v1.project_finder import settings

router = APIRouter(prefix="/project-finder")
router.include_router(settings.router)
