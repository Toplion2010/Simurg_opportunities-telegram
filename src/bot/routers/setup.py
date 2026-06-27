from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.core.config import Settings

router = Router(name="setup")

_WELCOME = """\
👋 <b>Welcome to Simurg Opportunities!</b>

Simurg Opportunities is an AI-powered channel that finds, analyzes, and publishes high-quality opportunities from trusted sources.

Instead of scrolling through dozens of Telegram channels, we do the work for you.

Every post is:
✅ AI-curated
✅ Clean and standardized
✅ Easy to read
✅ Focused on what actually matters

You'll find:
🎓 Scholarships
💼 Internships
🚀 Startup Programs
🏆 Competitions
💰 Grants
🔬 Research Opportunities
🌍 Fellowships
💻 Hackathons
🎯 Conferences
📚 Summer Schools
...and much more.

Some opportunities are marked with special hooks to highlight exclusive or particularly valuable ones — see the next message for the full guide.

Good luck, and don't miss your next opportunity. 🍀\
"""

_HOOKS = """\
🏷 <b>Opportunity Hooks Guide</b>

Special tags that mark opportunities worth extra attention:

🔥 <b>#PremiumOpportunity</b>
The best opportunities we find.

🚀 <b>#EarlyAccess</b>
Applications have just opened.

⭐ <b>#LimitedSpots</b>
Limited number of participants.

💰 <b>#PaidOpportunity</b>
Includes funding, salary, stipend, or prize money.

🧪 <b>#BetaTesting</b>
Early access to new products or programs.

🎁 <b>#Exclusive</b>
Rare or invite-only opportunities.

🌍 <b>#Worldwide</b>
Open to applicants from most countries.

⚡ <b>#ClosingSoon</b>
Deadline is approaching.

🏆 <b>#HighlyRecommended</b>
One of the strongest opportunities available.\
"""

_BIO = """\
⭐ Simurg Opportunities

The smartest place to discover scholarships, internships, hackathons, grants, fellowships, research programs, startup opportunities, and more.

Every opportunity is AI-curated, standardized, and summarized to help you find the best opportunities faster.

🚀 No spam.
🤖 AI-powered.
🌍 Global opportunities.
🎯 Built for ambitious students, founders, researchers, and professionals.\
"""


@router.message(Command("setup_channel"))
async def setup_channel(message: Message, bot: Bot, settings: Settings) -> None:
    chat_id = settings.DEST_CHANNEL_ID
    await bot.send_message(chat_id=chat_id, text=_WELCOME, parse_mode="HTML")
    await bot.send_message(chat_id=chat_id, text=_HOOKS, parse_mode="HTML")
    await message.answer(
        "✅ Channel messages sent.\n\n"
        "📋 <b>Channel description to copy-paste manually:</b>\n\n"
        + _BIO,
        parse_mode="HTML",
    )
