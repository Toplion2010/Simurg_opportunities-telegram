"""
Re-score every pending opportunity with an LLM judging the same 3-axis rubric
src/core/scoring.py computes with regex (coolness/fit/prestige, see that
module's docstring) -- a second opinion the regex scorer can't give itself,
since regex has no judgment, only pattern matches.

Usage:
    python -m scripts.ai_rescore_opportunities [--apply] [--limit N]

Runs read-only by default and prints exactly what it would change. Pass
--apply to write relevance/relevance_reason for every pending row the LLM
successfully scored. Rows the LLM call fails or returns malformed JSON for
are left untouched and reported at the end -- a bad LLM response must never
blank out a working regex score.

Uses the same Groq (OpenAI-compatible) client and model already wired into
src/processor/extractor.py's FieldExtractor for Telegram field extraction --
no new provider, no new key, and Groq's free tier is the reason this pipeline
already runs its real-time text extraction on it rather than a paid API.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import openai
from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy import select
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.session import create_session_factory

_MAX_REASON_LEN = 120  # Opportunity.relevance_reason is a String(120) column.
_CONCURRENCY = 5  # stays well under Groq's free-tier per-minute request cap.

_SYSTEM_PROMPT = """You are scoring a study/opportunity listing for a specific student profile \
using a strict 3-axis rubric. Score EXACTLY as specified -- this is a rubric to apply, not a \
judgment call to make from scratch.

AXIS 1 -- COOLNESS (0-40): can a Kazakhstani student actually reach this, and how good is the deal.
  0: in-person, priced, unfunded, non-Kazakhstan location, OR the listing restricts eligibility to \
US/other citizens or residents (a citizenship/residency bar).
  10-17: free or cheap (<= $50) in-person with no funding language, OR both online-ness and cost are \
genuinely unknown from the text.
  25-30: in-person, non-Kazakhstan, with PARTIAL funding language (scholarship / financial aid / \
stipend / grant mentioned, but not explicitly full travel+lodging coverage).
  38-40: online/remote/hybrid format, OR fully funded (tuition AND travel AND lodging), OR located \
in Kazakhstan and free/funded.

AXIS 2 -- FIT (0-40): match to this profile -- competitive programmer (Codeforces/ICPC), AI/ML \
builder and researcher, founder, full-stack engineer.
  34-40: AI/ML, competitive programming, hackathons, founder/startup language, or a CS/tech-context \
research program.
  22-28: adjacent software engineering (web/mobile/full-stack, data science/engineering, open source).
  10-16: loosely related -- generic STEM/tech/innovation/product language with no CS/AI keyword.
  0: everything else, INCLUDING chess, pure math olympiad, and sports -- even if some other \
qualifying word appears nearby in the same text. A bare word "competition" alone is not enough for \
the top tier.

AXIS 3 -- PRESTIGE (0-20): selectivity, brand recognition, and CONCRETE prize/output language.
  14-20: a flagship institution/org (MIT, Stanford, Google, ICPC, IOI, Y Combinator, etc.) and/or an \
explicit numeric selectivity claim ("15% acceptance", "only 20 spots").
  7-13: a real prize/scholarship/grant DOLLAR AMOUNT given TO the participant (not a program cost or \
tuition figure -- a "$1,875" camp fee is NOT a prize), OR vague selectivity language ("highly \
selective") with no number, OR a named-but-non-flagship org (a university/college/foundation/company).
  0: none of the above -- open enrollment, no cap, unknown organizer, generic/low-stakes.
  IMPORTANT: never count a listed cost/tuition/fee as a prize. Only a dollar figure the participant \
RECEIVES (a prize, award, scholarship, or grant) counts.

Given the opportunity's fields below, output STRICT JSON and nothing else, shaped exactly as:
{"coolness": <int 0-40>, "coolness_reason": "<under 8 words>", \
"fit": <int 0-40>, "fit_reason": "<under 8 words>", \
"prestige": <int 0-20>, "prestige_reason": "<under 8 words>"}
"""


class _LlmScore(BaseModel):
    coolness: int
    coolness_reason: str
    fit: int
    fit_reason: str
    prestige: int
    prestige_reason: str

    @field_validator("coolness")
    @classmethod
    def _coolness_range(cls, v: int) -> int:
        return max(0, min(40, v))

    @field_validator("fit")
    @classmethod
    def _fit_range(cls, v: int) -> int:
        return max(0, min(40, v))

    @field_validator("prestige")
    @classmethod
    def _prestige_range(cls, v: int) -> int:
        return max(0, min(20, v))


def _opportunity_text(opp: Opportunity) -> str:
    lines = [f"Title: {opp.title or '(none)'}"]
    if opp.description:
        lines.append(f"Description: {opp.description}")
    if opp.eligibility:
        lines.append(f"Eligibility: {opp.eligibility}")
    if opp.location:
        lines.append(f"Location: {opp.location}")
    if opp.cost:
        lines.append(f"Cost: {opp.cost}")
    if opp.organizer:
        lines.append(f"Organizer: {opp.organizer}")
    return "\n".join(lines)


@retry(
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=4, max=90),
    reraise=True,
)
async def _score_one(client: openai.AsyncOpenAI, model: str, opp: Opportunity) -> _LlmScore:
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _opportunity_text(opp)},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=300,
    )
    raw = response.choices[0].message.content or "{}"
    return _LlmScore.model_validate(json.loads(raw))


async def run(apply: bool, limit: int | None) -> int:
    settings = Settings()
    if not settings.GROQ_API_KEY:
        print("GROQ_API_KEY not set -- nothing to do.")
        return 1

    client = openai.AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url=settings.GROQ_BASE_URL)
    model = settings.GROQ_MODEL

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            stmt = select(Opportunity).where(Opportunity.status == OpportunityStatus.pending)
            if limit:
                stmt = stmt.limit(limit)
            opps = (await session.execute(stmt)).scalars().all()

            sem = asyncio.Semaphore(_CONCURRENCY)
            failures: list[tuple[int, str]] = []
            changed = 0

            async def handle(opp: Opportunity) -> None:
                nonlocal changed
                async with sem:
                    try:
                        result = await _score_one(client, model, opp)
                    except (openai.RateLimitError, openai.APIError, json.JSONDecodeError, ValidationError) as e:
                        failures.append((opp.id, str(e)[:120]))
                        return

                total = result.coolness + result.fit + result.prestige
                reason = (
                    f"cool {result.coolness}/40 ({result.coolness_reason}) + "
                    f"fit {result.fit}/40 ({result.fit_reason}) + "
                    f"prestige {result.prestige}/20 ({result.prestige_reason})"
                )
                if len(reason) > _MAX_REASON_LEN:
                    reason = reason[: _MAX_REASON_LEN - 3] + "..."

                old = opp.relevance
                print(f"  #{opp.id:<5} {old} -> {total}/100  ({reason})  {(opp.title or '')[:40]}")
                if total != old:
                    changed += 1
                if apply:
                    opp.relevance = total
                    opp.relevance_reason = reason

            await asyncio.gather(*(handle(opp) for opp in opps))

            print(f"\n{changed} of {len(opps)} pending opportunities would change score.")
            if failures:
                print(f"{len(failures)} rows failed the AI call and were left untouched:")
                for opp_id, err in failures:
                    print(f"  #{opp_id}: {err}")

            if not apply:
                print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
                await session.rollback()
                return 0

            await session.commit()
            print("\nApplied.")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(prog="ai_rescore_opportunities")
    parser.add_argument(
        "--apply", action="store_true", help="Commit the changes (default: dry run)."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only score this many pending rows (for testing)."
    )
    args = parser.parse_args()
    return asyncio.run(run(args.apply, args.limit))


if __name__ == "__main__":
    sys.exit(main())
