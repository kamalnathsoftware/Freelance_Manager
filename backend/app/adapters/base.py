"""Platform adapter framework.

Tiers (see docs/INTEGRATIONS.md):
  api    - official OAuth/API
  email  - parse the user's own notification emails
  manual - assisted: deep links, copy-ready exports, user-driven browser extension

Adapters NEVER automate logins, scrape, bypass CAPTCHAs or auto-submit bids.
"""

from __future__ import annotations

import enum
from abc import ABC
from dataclasses import dataclass, field
from typing import Any


class Capability(enum.StrEnum):
    sync_profile = "sync_profile"
    sync_gigs = "sync_gigs"
    fetch_jobs = "fetch_jobs"
    fetch_messages = "fetch_messages"
    send_message = "send_message"
    submit_proposal = "submit_proposal"
    sync_orders = "sync_orders"


class NotSupportedError(Exception):
    """The platform/tier doesn't support this action. UI should use the manual fallback."""


class NotConfiguredError(Exception):
    """API credentials are missing or API access hasn't been granted yet."""


@dataclass
class AdapterContext:
    """What an adapter needs to talk to a platform, decrypted by the caller."""

    account_id: str
    access_token: str | None = None
    refresh_token: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfileData:
    headline: str = ""
    bio: str = ""
    skills: list[str] = field(default_factory=list)
    hourly_rate: float | None = None
    username: str = ""
    profile_url: str = ""


class PlatformAdapter(ABC):
    key: str
    display_name: str
    tier: str  # api | email | manual
    base_url: str = ""
    capabilities_set: frozenset[Capability] = frozenset()
    # {path-template: description}; used to build deep links so the user finishes the action themselves.
    deep_links: dict[str, str] = {}

    def capabilities(self) -> set[Capability]:
        return set(self.capabilities_set)

    def supports(self, cap: Capability) -> bool:
        return cap in self.capabilities_set

    def _require(self, cap: Capability) -> None:
        if not self.supports(cap):
            raise NotSupportedError(f"{self.display_name} does not support {cap.value}")

    def deep_link(self, name: str, **params: str) -> str | None:
        tpl = self.deep_links.get(name)
        return tpl.format(**params) if tpl else None

    # ---- actions (all optional; default: unsupported) ----
    async def connect(self, ctx: AdapterContext) -> dict[str, Any]:
        return {}

    async def sync_profile(self, ctx: AdapterContext) -> ProfileData:
        self._require(Capability.sync_profile)
        raise NotSupportedError

    async def sync_gigs(self, ctx: AdapterContext) -> list[dict[str, Any]]:
        self._require(Capability.sync_gigs)
        raise NotSupportedError

    async def fetch_jobs(self, ctx: AdapterContext, query: dict[str, Any]) -> list[dict[str, Any]]:
        self._require(Capability.fetch_jobs)
        raise NotSupportedError

    async def fetch_messages(self, ctx: AdapterContext) -> list[dict[str, Any]]:
        self._require(Capability.fetch_messages)
        raise NotSupportedError

    async def send_message(self, ctx: AdapterContext, thread_id: str, body: str) -> dict[str, Any]:
        self._require(Capability.send_message)
        raise NotSupportedError

    async def submit_proposal(
        self, ctx: AdapterContext, job_id: str, proposal: dict[str, Any]
    ) -> dict[str, Any]:
        """Callers MUST have recorded explicit user approval before invoking this."""
        self._require(Capability.submit_proposal)
        raise NotSupportedError

    async def sync_orders(self, ctx: AdapterContext) -> list[dict[str, Any]]:
        self._require(Capability.sync_orders)
        raise NotSupportedError
