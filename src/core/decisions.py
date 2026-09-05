"""Pure predicate over an already-loaded Opportunity: was its approval a real
human decision, or just src/routines/daily_digest.py auto-approving because
the score crossed AUTO_APPROVE_SCORE?

daily_digest.py sets `digested_at` and `scheduled_at` to the exact same `now`
only in its auto-approve branch -- a human approval via the review queue
never touches `scheduled_at` at all unless later scheduled separately, so
`scheduled_at == digested_at` is the tell. Rejected rows are always a real
human decision: there is no auto-reject path.

Shared by scripts/list_decisions.py and scripts/validate_scoring_rubric.py
so the heuristic exists in exactly one place.
"""
from src.core.enums import OpportunityStatus
from src.db.models.opportunity import Opportunity


def is_auto_approval(opp: Opportunity) -> bool:
    return (
        opp.status in (OpportunityStatus.approved, OpportunityStatus.published)
        and opp.digested_at is not None
        and opp.scheduled_at == opp.digested_at
    )
