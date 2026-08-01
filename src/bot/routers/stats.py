from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import OpportunityStatus
from src.db.repositories.opportunity import OpportunityRepository

router = Router(name="stats")

RECENT_DAYS = 7
RECENT_LIST_LIMIT = 10

_STATUS_ORDER = [
    OpportunityStatus.pending,
    OpportunityStatus.approved,
    OpportunityStatus.published,
    OpportunityStatus.rejected,
]
_STATUS_LABELS = {
    OpportunityStatus.pending: "🕓 Pending",
    OpportunityStatus.approved: "✅ Approved",
    OpportunityStatus.published: "📤 Published",
    OpportunityStatus.rejected: "❌ Rejected",
}


@router.message(Command("stats"))
@router.message(F.text == "📊 Stats")
async def show_stats(message: Message, session: AsyncSession) -> None:
    repo = OpportunityRepository(session)

    by_status = await repo.count_by_status()
    by_category = await repo.count_by_category()
    since = datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(days=RECENT_DAYS)
    recent = await repo.get_recently_published(since)

    total = sum(by_status.values())
    lines = ["📊 <b>Opportunity Stats</b>", "", f"Total: <b>{total}</b>"]
    for status in _STATUS_ORDER:
        lines.append(f"{_STATUS_LABELS[status]}: {by_status.get(status, 0)}")

    lines.append("")
    lines.append("<b>By category</b>")
    if by_category:
        for category, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
            lines.append(f"🏷 {category or 'Unknown'}: {count}")
    else:
        lines.append("No opportunities yet.")

    lines.append("")
    lines.append(f"<b>Published in the last {RECENT_DAYS} days</b> ({len(recent)})")
    if recent:
        for opp in recent[:RECENT_LIST_LIMIT]:
            when = opp.published_at.strftime("%Y-%m-%d %H:%M") if opp.published_at else "?"
            lines.append(f"• {opp.title or 'Untitled'} — {when} UTC")
        if len(recent) > RECENT_LIST_LIMIT:
            lines.append(f"…and {len(recent) - RECENT_LIST_LIMIT} more")
    else:
        lines.append("None yet.")

    await message.answer("\n".join(lines), parse_mode="HTML")
