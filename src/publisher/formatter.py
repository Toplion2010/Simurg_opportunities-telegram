import re

from src.db.models.opportunity import Opportunity

_CATEGORY_TAGS: dict[str, str] = {
    "Internship":    "#Internship",
    "Scholarship":   "#Scholarship",
    "Fellowship":    "#Fellowship",
    "Research":      "#Research",
    "Competition":   "#Competition",
    "Olympiad":      "#Olympiad",
    "Hackathon":     "#Hackathon",
    "Startup":       "#Startup",
    "Accelerator":   "#Accelerator",
    "Incubator":     "#Incubator",
    "Grant":         "#Grant",
    "Conference":    "#Conference",
    "SummerProgram": "#SummerProgram",
    "Exchange":      "#Exchange",
    "Volunteer":     "#Volunteer",
    "Job":           "#Job",
}


def _v(value: str | None, fallback: str = "Unknown") -> str:
    return value.strip() if value and value.strip() else fallback


def _bold(text: str) -> str:
    return f"<b>{text}</b>"


def _split_paragraphs(text: str) -> list[str]:
    chunks = [c.strip() for c in re.split(r"\n{2,}", text) if c.strip()]
    if len(chunks) > 1:
        return chunks

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    paragraphs = []
    for i in range(0, len(sentences), 2):
        para = " ".join(sentences[i:i + 2]).strip()
        if para:
            paragraphs.append(para)
    return paragraphs or [text]


def format_opportunity(opp: Opportunity) -> str:
    parts: list[str] = []

    # Hooks — already formatted display strings (e.g. "🔥 #PremiumOpportunity")
    if opp.hooks:
        hook_labels = [_bold(h) for h in opp.hooks]
        parts.append("  ".join(hook_labels))
        parts.append("<b>——————————————</b>")
        parts.append("")

    # Title
    title = _v(opp.title, "Opportunity")
    parts.append(_bold(f"✨ {title}"))
    parts.append("")

    # Category/Location/Organizer/Duration/Deadline are intentionally omitted here —
    # they're short values that always fit untruncated in the card image's meta rows,
    # so repeating them in the caption is pure duplication. Eligibility and Prize/Funding
    # stay below because the image truncates those; the caption gives the full text.

    parts.append("<b>·  ·  ·</b>")
    parts.append("")

    # Eligibility
    if opp.eligibility and _v(opp.eligibility) != "Unknown":
        parts.append(f"👤 {_bold('Who can apply:')}")
        parts.append(opp.eligibility)
        parts.append("")

    # Prize / Funding
    prize = opp.rewards or opp.cost
    if prize and _v(prize) != "Unknown":
        parts.append(f"💰 {_bold('Prize / Funding:')}")
        parts.append(prize)
        parts.append("")

    # Additional info — catch-all facts an AI split/extraction couldn't fit a
    # dedicated field (acceptance rate, contact email, sub-track specifics, etc.)
    if opp.extra_notes and _v(opp.extra_notes) != "Unknown":
        parts.append(f"ℹ️ {_bold('Additional info:')}")
        parts.append(opp.extra_notes)
        parts.append("")

    # Description
    if opp.description and _v(opp.description) != "Unknown":
        parts.append(f"📝 {_bold('About:')}")
        for para in _split_paragraphs(opp.description):
            parts.append(para)
            parts.append("")

    # Apply link — HTML anchor
    apply = _v(opp.apply_link, "")
    if apply:
        parts.append(f'🔗 {_bold("Apply Now →")} <a href="{apply}">{apply}</a>')
        parts.append("")

    # Additional links — e.g. an Instagram page or secondary info page that isn't
    # the primary application link but was mentioned in the source text.
    if opp.additional_links:
        links_line = "  ".join(
            f'<a href="{link}">{link}</a>' for link in opp.additional_links
        )
        parts.append(f"🔗 {_bold('Also see:')} {links_line}")
        parts.append("")

    # Tags footer
    category_tag = _CATEGORY_TAGS.get(opp.category.value, "") if opp.category else ""
    tag_line = f"{category_tag} #SimurgOpportunities".strip()
    parts.append("——")
    parts.append(f"<i>{tag_line}</i>")

    text = "\n".join(parts).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
