from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.adapters.rules import RULES
from app.api.deps import CurrentUser
from app.services import ai

router = APIRouter(prefix="/ai", tags=["ai"])


class RewriteIn(BaseModel):
    kind: Literal["headline", "bio", "gig_title", "gig_description"]
    text: str = Field(min_length=1, max_length=10000)
    platform: str = "direct"
    tone: str = "professional"
    keywords: list[str] = []


class Suggestion(BaseModel):
    text: str
    ai_generated: bool = True
    requires_approval: bool = True


class KeywordsIn(BaseModel):
    title: str
    description: str = ""


@router.post("/rewrite", response_model=Suggestion)
async def rewrite(body: RewriteIn, _: CurrentUser) -> Suggestion:
    r = RULES.get(body.platform, RULES["direct"])
    limit = {
        "headline": r.headline_max, "bio": r.bio_max,
        "gig_title": r.gig_title_max, "gig_description": r.gig_description_max,
    }[body.kind]  # fmt: skip
    text = await ai.rewrite(
        body.kind.replace("_", " "), body.text, body.tone, body.platform, limit, body.keywords
    )
    return Suggestion(text=text)


@router.post("/keywords", response_model=list[str])
async def keywords(body: KeywordsIn, _: CurrentUser) -> list[str]:
    return await ai.suggest_keywords(body.title, body.description)
