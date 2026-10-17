"""Proposal tracker rules: status -> reply bookkeeping and the knock-on effect on the linked lead."""

from datetime import date

from app.models import PFLead, PFProposal
from app.services.project_finder.outreach import STATUSES

PROPOSAL_STATUSES = ("sent", "replied", "interview", "won", "lost", "no_response")
REPLIED_STATUSES = ("replied", "interview", "won")  # a reply is implied by these


def sync_reply(p: PFProposal, today: date) -> None:
    """A proposal that is replied / in interview / won has had a reply: stamp the date once."""
    if p.status in REPLIED_STATUSES and p.replied_on is None:
        p.replied_on = max(today, p.sent_on)


def advance_lead(lead: PFLead | None, proposal_status: str, *, created: bool) -> None:
    """Keep the CRM in step so nothing is entered twice:
    - a proposal is sent    -> an earlier-stage lead becomes "Proposal sent"
    - a proposal is won     -> the lead becomes "Won" (follow-ups cleared)
    A lost proposal leaves the lead alone: you may still win other work from them."""
    if lead is None or lead.status in ("won", "lost"):
        return
    if proposal_status == "won":
        lead.status, lead.next_follow_up = "won", None
    elif created and STATUSES.index(lead.status) < STATUSES.index("proposal_sent"):
        lead.status = "proposal_sent"
