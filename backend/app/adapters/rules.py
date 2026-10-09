"""Per-platform field limits used by the profile/gig editors (defaults; verify against current platform docs)."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PlatformRules:
    headline_max: int
    bio_max: int
    skills_max: int
    gig_title_max: int = 0  # 0 = platform has no gigs
    gig_description_max: int = 0
    gig_tags_max: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


RULES: dict[str, PlatformRules] = {
    "fiverr": PlatformRules(0, 600, 15, gig_title_max=80, gig_description_max=1200, gig_tags_max=5),
    "upwork": PlatformRules(70, 5000, 15),
    "freelancer": PlatformRules(100, 2000, 20),
    "peopleperhour": PlatformRules(
        100, 3000, 20, gig_title_max=70, gig_description_max=2000, gig_tags_max=8
    ),
    "toptal": PlatformRules(120, 4000, 30),
    "guru": PlatformRules(100, 3000, 20),
    "linkedin": PlatformRules(
        220, 2600, 50, gig_title_max=100, gig_description_max=2000, gig_tags_max=10
    ),
    "contra": PlatformRules(120, 2000, 20),
    "direct": PlatformRules(
        300, 10000, 100, gig_title_max=200, gig_description_max=10000, gig_tags_max=20
    ),
}
