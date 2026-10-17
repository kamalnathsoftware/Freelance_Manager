from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.deps import DB, CurrentUser
from app.api.v1.project_finder.common import TzStr, clean_list
from app.schemas import ORM
from app.services.project_finder import get_pf_settings

router = APIRouter(tags=["project-finder"])


class SettingsIn(BaseModel):
    skills: list[str] | None = None
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    min_store_score: int | None = Field(default=None, ge=0, le=100)
    daily_goal: int | None = Field(default=None, ge=1, le=100)
    my_name: str | None = Field(default=None, max_length=120)
    home_tz: TzStr | None = None
    work_start_hour: int | None = Field(default=None, ge=0, le=23)
    work_end_hour: int | None = Field(default=None, ge=1, le=24)

    @field_validator("skills", "include_keywords", "exclude_keywords")
    @classmethod
    def _clean(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else clean_list(v)


class SettingsOut(ORM):
    skills: list[str]
    include_keywords: list[str]
    exclude_keywords: list[str]
    min_store_score: int
    daily_goal: int
    my_name: str
    home_tz: str
    work_start_hour: int
    work_end_hour: int
    created_at: datetime


@router.get("/settings", response_model=SettingsOut)
async def read_settings(user: CurrentUser, db: DB) -> object:
    row = await get_pf_settings(db, user.id)
    await db.commit()
    return row


@router.put("/settings", response_model=SettingsOut)
async def update_settings(body: SettingsIn, user: CurrentUser, db: DB) -> object:
    row = await get_pf_settings(db, user.id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    start = changes.get("work_start_hour", row.work_start_hour)
    end = changes.get("work_end_hour", row.work_end_hour)
    if end <= start:
        raise HTTPException(422, "work_end_hour must be after work_start_hour")
    if "home_tz" in changes and not changes["home_tz"]:
        raise HTTPException(422, "home_tz cannot be empty")
    for k, v in changes.items():
        setattr(row, k, v)
    await db.commit()
    return row
