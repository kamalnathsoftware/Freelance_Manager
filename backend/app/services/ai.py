"""Claude-powered writing assistant. Output is always a *suggestion*: callers must get user approval."""

import httpx
from fastapi import HTTPException

from app.core.config import get_settings

TONES = {"professional", "friendly", "confident", "concise", "persuasive"}
API_URL = "https://api.anthropic.com/v1/messages"


async def complete(system: str, prompt: str, max_tokens: int = 800) -> str:
    s = get_settings()
    if not s.anthropic_api_key:
        raise HTTPException(503, "AI assistant is not configured (set ANTHROPIC_API_KEY)")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            API_URL,
            headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": s.ai_model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    if r.status_code != 200:
        raise HTTPException(502, "AI provider error")
    return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()


async def rewrite(
    kind: str, text: str, tone: str, platform: str, limit: int, keywords: list[str]
) -> str:
    if tone not in TONES:
        raise HTTPException(422, f"tone must be one of {sorted(TONES)}")
    system = (
        "You are an expert freelance-profile copywriter. Return ONLY the rewritten text, "
        "no preamble, no quotes. Never invent credentials, clients or numbers not in the source."
    )
    prompt = (
        f"Rewrite this freelancer {kind} for {platform}. Tone: {tone}. "
        f"Maximum {limit or 'no'} characters. "
        + (
            f"Naturally include these keywords where truthful: {', '.join(keywords)}. "
            if keywords
            else ""
        )
        + f"\n\nSOURCE:\n{text}"
    )
    out = await complete(system, prompt)
    return out[:limit] if limit else out


async def suggest_keywords(title: str, description: str) -> list[str]:
    out = await complete(
        "Return 8-12 comma-separated search keywords freelance buyers use. No other text.",
        f"Title: {title}\nDescription: {description}",
        200,
    )
    return [k.strip() for k in out.split(",") if k.strip()]
