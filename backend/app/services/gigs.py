from typing import Any

from app.adapters.registry import get_adapter
from app.adapters.rules import RULES
from app.models import Gig, GigPackage, GigPlatformListing, PlatformAccount
from app.services.profiles import fit


def adapt_for_platform(gig: Gig, platform: str) -> dict[str, Any]:
    r = RULES[platform]
    return {
        "title": fit(gig.title, r.gig_title_max),
        "description": fit(gig.description, r.gig_description_max),
        "tags": list(gig.tags)[: r.gig_tags_max] if r.gig_tags_max else list(gig.tags),
    }


def effective(gig: Gig, listing: GigPlatformListing, platform: str) -> dict[str, Any]:
    base = adapt_for_platform(gig, platform)
    base.update({k: v for k, v in listing.overrides.items() if k in base})
    return base


def checklist(
    gig: Gig, packages: list[GigPackage], listing: GigPlatformListing, acc: PlatformAccount
) -> list[dict[str, Any]]:
    r, eff = RULES[acc.platform], effective(gig, listing, acc.platform)
    items = [
        ("Title is set and within the platform limit", 0 < len(eff["title"]) <= r.gig_title_max),
        ("Description is at least 120 characters", len(eff["description"]) >= 120),
        (
            f"Description within {r.gig_description_max} characters",
            len(eff["description"]) <= r.gig_description_max,
        ),
        ("At least one package with a price", any(p.price > 0 for p in packages)),
        ("Category is chosen", bool(gig.category)),
        ("At least 3 tags", len(eff["tags"]) >= 3),
        ("Gallery has at least one image", bool(gig.gallery)),
        ("FAQ has at least one entry", bool(gig.faq)),
    ]
    return [{"item": i, "done": ok} for i, ok in items]


def export_listing(
    gig: Gig, packages: list[GigPackage], listing: GigPlatformListing, acc: PlatformAccount
) -> dict[str, Any]:
    """Copy-ready field blocks (user pastes these into the platform; nothing is auto-submitted)."""
    r, eff, adapter = (
        RULES[acc.platform],
        effective(gig, listing, acc.platform),
        get_adapter(acc.platform),
    )
    fields = [
        {"field": "title", "value": eff["title"], "limit": r.gig_title_max},
        {"field": "description", "value": eff["description"], "limit": r.gig_description_max},
        {"field": "tags", "value": ", ".join(eff["tags"]), "limit": r.gig_tags_max},
    ]
    for f in fields:
        if f["field"] == "tags":
            f["length"] = len(eff["tags"])
        else:
            f["length"] = len(str(f["value"]))
        f["over_limit"] = bool(f["limit"]) and f["length"] > f["limit"]
    return {
        "platform": acc.platform,
        "fields": fields,
        "packages": [
            {
                "tier": p.tier,
                "name": p.name,
                "price": p.price,
                "delivery_days": p.delivery_days,
                "revisions": p.revisions,
                "description": p.description,
                "features": p.features,
            }  # fmt: skip
            for p in sorted(packages, key=lambda p: ["basic", "standard", "premium"].index(p.tier))
        ],
        "faq": gig.faq,
        "requirements": gig.requirements,
        "open_on_platform": adapter.deep_link("new_gig", username=acc.username) or adapter.base_url,
    }


def performance(listings: list[GigPlatformListing]) -> dict[str, Any]:
    imp = sum(int(li.metrics.get("impressions", 0)) for li in listings)
    clk = sum(int(li.metrics.get("clicks", 0)) for li in listings)
    orders = sum(int(li.metrics.get("orders", 0)) for li in listings)
    return {
        "impressions": imp, "clicks": clk, "orders": orders,
        "ctr": round(clk / imp, 4) if imp else 0.0,
        "conversion": round(orders / clk, 4) if clk else 0.0,
    }  # fmt: skip
