from typing import Any

import httpx

from app.adapters.base import (
    AdapterContext,
    Capability,
    NotConfiguredError,
    PlatformAdapter,
    ProfileData,
)

C = Capability


class UpworkAdapter(PlatformAdapter):
    """Official Upwork GraphQL API. Needs approved API keys; until then methods raise NotConfiguredError."""

    key, display_name, tier = "upwork", "Upwork", "api"
    base_url = "https://www.upwork.com"
    capabilities_set = frozenset(
        {
            C.sync_profile,
            C.fetch_jobs,
            C.fetch_messages,
            C.send_message,
            C.submit_proposal,
            C.sync_orders,
        }
    )
    deep_links = {
        "job": "https://www.upwork.com/jobs/{job_id}",
        "messages": "https://www.upwork.com/ab/messages/",
        "profile": "https://www.upwork.com/freelancers/settings/profile",
    }

    async def sync_profile(self, ctx: AdapterContext) -> ProfileData:
        if not ctx.access_token:
            raise NotConfiguredError("Upwork API access has not been granted for this account yet")
        # TODO(api-access): GraphQL query against https://api.upwork.com/graphql once keys are approved.
        raise NotConfiguredError("Upwork GraphQL sync pending API approval")


class FreelancerAdapter(PlatformAdapter):
    """Freelancer.com REST API (OAuth2). Profile sync uses /users/0.1/self."""

    key, display_name, tier = "freelancer", "Freelancer.com", "api"
    base_url = "https://www.freelancer.com"
    api_url = "https://www.freelancer.com/api"
    capabilities_set = frozenset(
        {
            C.sync_profile,
            C.fetch_jobs,
            C.fetch_messages,
            C.send_message,
            C.submit_proposal,
            C.sync_orders,
        }
    )
    deep_links = {
        "job": "https://www.freelancer.com/projects/{job_id}",
        "messages": "https://www.freelancer.com/messages",
    }

    async def sync_profile(self, ctx: AdapterContext) -> ProfileData:
        if not ctx.access_token:
            raise NotConfiguredError("Freelancer.com is not connected")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{self.api_url}/users/0.1/self/",
                headers={"freelancer-oauth-v1": ctx.access_token},
            )
        r.raise_for_status()
        res: dict[str, Any] = r.json().get("result", {})
        return ProfileData(
            headline=res.get("tagline") or "",
            bio=res.get("profile_description") or "",
            username=res.get("username") or "",
            profile_url=f"{self.base_url}/u/{res.get('username', '')}",
        )


class EmailManualAdapter(PlatformAdapter):
    """No public API: activity arrives via email ingestion / browser extension; actions are deep links."""

    def __init__(
        self, key: str, name: str, base: str, links: dict[str, str], has_gigs: bool = False
    ) -> None:
        self.key, self.display_name, self.tier, self.base_url = key, name, "email", base
        self.deep_links = links
        caps = {C.fetch_jobs, C.fetch_messages, C.sync_orders}  # via parsed emails only
        if has_gigs:
            caps.add(C.sync_gigs)  # via manual entry / extension capture
        self.capabilities_set = frozenset(caps)


class DirectAdapter(PlatformAdapter):
    """Direct clients: everything is native to this app."""

    key, display_name, tier = "direct", "Direct clients", "manual"
    capabilities_set = frozenset(
        {C.sync_profile, C.sync_gigs, C.fetch_jobs, C.fetch_messages, C.send_message, C.sync_orders}
    )


def _em(key: str, name: str, base: str, has_gigs: bool = False, **links: str) -> EmailManualAdapter:
    return EmailManualAdapter(key, name, base, links, has_gigs)


ADAPTERS: dict[str, PlatformAdapter] = {
    a.key: a
    for a in [
        UpworkAdapter(),
        FreelancerAdapter(),
        _em(
            "fiverr",
            "Fiverr",
            "https://www.fiverr.com",
            True,
            inbox="https://www.fiverr.com/inbox",
            orders="https://www.fiverr.com/users/{username}/manage_orders",
            manage_gigs="https://www.fiverr.com/users/{username}/manage_gigs",
            new_gig="https://www.fiverr.com/seller_dashboard",
        ),
        _em(
            "peopleperhour",
            "PeoplePerHour",
            "https://www.peopleperhour.com",
            True,
            inbox="https://www.peopleperhour.com/site/messages",
            job="https://www.peopleperhour.com/freelance-jobs/{job_id}",
        ),
        _em("toptal", "Toptal", "https://www.toptal.com", inbox="https://talent.toptal.com/portal"),
        _em("guru", "Guru", "https://www.guru.com", inbox="https://www.guru.com/messages"),
        _em(
            "linkedin",
            "LinkedIn Services",
            "https://www.linkedin.com",
            True,
            inbox="https://www.linkedin.com/messaging/",
            services="https://www.linkedin.com/services/",
        ),
        _em("contra", "Contra", "https://contra.com", inbox="https://contra.com/inbox"),
        DirectAdapter(),
    ]
}


def get_adapter(key: str) -> PlatformAdapter:
    try:
        return ADAPTERS[key]
    except KeyError:
        raise KeyError(f"Unknown platform: {key}") from None
