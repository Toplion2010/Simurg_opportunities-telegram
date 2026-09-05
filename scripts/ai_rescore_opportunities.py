"""
Re-score every pending opportunity with an LLM judging the same 3-axis rubric
src/core/scoring.py computes with regex (coolness/fit/prestige, see that
module's docstring) -- a second opinion the regex scorer can't give itself,
since regex has no judgment, only pattern matches.

Usage:
    python -m scripts.ai_rescore_opportunities [--apply] [--limit N]

Runs read-only by default and prints exactly what it would change. Pass
--apply to write relevance/relevance_reason for every pending row the LLM
successfully scored, committing every _COMMIT_BATCH_SIZE rows so a timeout
or cancellation only loses the current partial batch. Rows already scored
by this script (relevance_reason starting with "AI: ") are skipped on the
next run, so re-dispatching after an interruption resumes rather than
redoing finished work. Rows the LLM call fails or returns malformed JSON
for are left untouched and reported at the end -- a bad LLM response must
never blank out a working regex score.

Uses the same Groq (OpenAI-compatible) client and model already wired into
src/processor/extractor.py's FieldExtractor for Telegram field extraction --
no new provider, no new key, and Groq's free tier is the reason this pipeline
already runs its real-time text extraction on it rather than a paid API.
"""

import argparse
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import openai
from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy import or_, select, update
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import Settings
from src.core.enums import OpportunityStatus
from src.db.base import create_engine
from src.db.models.opportunity import Opportunity
from src.db.session import create_session_factory

_MAX_REASON_LEN = 120  # Opportunity.relevance_reason is a String(120) column.
_AI_MARKER = "AI: "  # prefix so a rerun can skip rows this script already wrote
# Sequential, not concurrent: a first pass at 5-way concurrency hit Groq's
# free-tier per-minute request cap on the very first batch (9 of 10 calls
# failed, most as 429s). One request at a time, paced, actually finishes
# instead of retrying into the same wall.
_REQUEST_PACING_SECONDS = 2.0
# Real-world latency (reasoning model, free tier) runs ~15-20s/call even with
# reasoning_effort=low, on top of the pacing sleep -- a first 484-row --apply
# run only got through 131 rows in the 60-minute job timeout and was killed,
# and since commit() only ran once at the very end, all 131 rows of work were
# lost. Commit every _COMMIT_BATCH_SIZE rows instead so a timeout/cancel only
# loses the current partial batch, and skip already-AI-scored rows up front
# so a rerun resumes rather than redoing finished work.
_COMMIT_BATCH_SIZE = 20

# Groq's free tier also caps openai/gpt-oss-120b at a per-day (rolling
# window) token budget separate from the per-minute cap -- once it's
# exhausted, 429s name the exact wait ("...on tokens per day (TPD): ...
# Please try again in 1m48.432s."). The default exponential backoff gives
# up (max 90s wait, 6 attempts) long before that window reopens, so most
# rows would be wrongly reported as failed. Parse the hint and wait exactly
# that long instead, capped so one stuck row can't stall the whole run.
_RETRY_AFTER_RE = re.compile(r"try again in (?:(?P<minutes>\d+)m)?(?P<seconds>[\d.]+)s")
_MAX_RATE_LIMIT_WAIT_SECONDS = 300.0

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


def _opportunity_text(opp: dict) -> str:
    lines = [f"Title: {opp['title'] or '(none)'}"]
    if opp["description"]:
        lines.append(f"Description: {opp['description']}")
    if opp["eligibility"]:
        lines.append(f"Eligibility: {opp['eligibility']}")
    if opp["location"]:
        lines.append(f"Location: {opp['location']}")
    if opp["cost"]:
        lines.append(f"Cost: {opp['cost']}")
    if opp["organizer"]:
        lines.append(f"Organizer: {opp['organizer']}")
    return "\n".join(lines)


def _groq_wait(retry_state):
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, openai.RateLimitError):
        m = _RETRY_AFTER_RE.search(str(exc))
        if m:
            wait_s = (int(m.group("minutes") or 0) * 60) + float(m.group("seconds")) + 1
            return min(wait_s, _MAX_RATE_LIMIT_WAIT_SECONDS)
    return wait_exponential(multiplier=2, min=4, max=90)(retry_state)


@retry(
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    stop=stop_after_attempt(8),
    wait=_groq_wait,
    reraise=True,
)
async def _score_one(client: openai.AsyncOpenAI, model: str, opp: dict) -> _LlmScore:
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _opportunity_text(opp)},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        # gpt-oss-120b is a reasoning model -- its chain-of-thought counts
        # against max_tokens before the JSON is emitted, so a low budget here
        # truncates mid-reasoning and Groq's json_object validator rejects
        # the incomplete output. reasoning_effort keeps that chain-of-thought
        # short in the first place rather than just hoping the token budget
        # covers whatever length it picks.
        max_tokens=1024,
        extra_body={"reasoning_effort": "low"},
    )
    raw = response.choices[0].message.content or "{}"
    return _LlmScore.model_validate(json.loads(raw))


async def _flush_updates(session_factory, updates: list[tuple[int, int, str]]) -> None:
    """Write a batch of (id, relevance, reason) via a short-lived session.

    Opened and closed just for this write so the connection is never sitting
    idle across the many seconds spent waiting on Groq between batches --
    that idle time is exactly what let Neon drop the connection out from
    under the old single-session-for-the-whole-run design.
    """
    async with session_factory() as session:
        for opp_id, relevance, reason in updates:
            await session.execute(
                update(Opportunity)
                .where(Opportunity.id == opp_id)
                .values(relevance=relevance, relevance_reason=reason)
            )
        await session.commit()


async def run(apply: bool, limit: int | None, count_only: bool = False) -> int:
    settings = Settings()
    if not count_only and not settings.GROQ_API_KEY:
        print("GROQ_API_KEY not set -- nothing to do.")
        return 1

    client = (
        None
        if count_only
        else openai.AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url=settings.GROQ_BASE_URL)
    )
    model = settings.GROQ_MODEL

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            stmt = (
                select(Opportunity)
                .where(Opportunity.status == OpportunityStatus.pending)
                .where(
                    or_(
                        Opportunity.relevance_reason.is_(None),
                        ~Opportunity.relevance_reason.like(f"{_AI_MARKER}%"),
                    )
                )
                .order_by(Opportunity.id)
            )
            if limit:
                stmt = stmt.limit(limit)
            opps = (await session.execute(stmt)).scalars().all()

            if count_only:
                print(f"{len(opps)} pending opportunities still need AI scoring.")
                return 0

            rows = [
                {
                    "id": o.id,
                    "relevance": o.relevance,
                    "title": o.title,
                    "description": o.description,
                    "eligibility": o.eligibility,
                    "location": o.location,
                    "cost": o.cost,
                    "organizer": o.organizer,
                }
                for o in opps
            ]
        # Session closed here -- no DB connection is held during the LLM loop below.

        failures: list[tuple[int, str]] = []
        changed = 0
        pending_updates: list[tuple[int, int, str]] = []

        for i, row in enumerate(rows):
            if i > 0:
                await asyncio.sleep(_REQUEST_PACING_SECONDS)

            try:
                result = await _score_one(client, model, row)
            except (openai.RateLimitError, openai.APIError, json.JSONDecodeError, ValidationError) as e:
                failures.append((row["id"], str(e)[:300]))
                continue

            total = result.coolness + result.fit + result.prestige
            reason = (
                f"{_AI_MARKER}cool {result.coolness}/40 ({result.coolness_reason}) + "
                f"fit {result.fit}/40 ({result.fit_reason}) + "
                f"prestige {result.prestige}/20 ({result.prestige_reason})"
            )
            if len(reason) > _MAX_REASON_LEN:
                reason = reason[: _MAX_REASON_LEN - 3] + "..."

            old = row["relevance"]
            print(f"  #{row['id']:<5} {old} -> {total}/100  ({reason})  {(row['title'] or '')[:40]}")
            if total != old:
                changed += 1
            if apply:
                pending_updates.append((row["id"], total, reason))
                if len(pending_updates) >= _COMMIT_BATCH_SIZE:
                    await _flush_updates(session_factory, pending_updates)
                    pending_updates = []

        print(f"\n{changed} of {len(rows)} pending opportunities would change score.")
        if failures:
            print(f"{len(failures)} rows failed the AI call and were left untouched:")
            for opp_id, err in failures:
                print(f"  #{opp_id}: {err}")

        if not apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
            return 0

        if pending_updates:
            await _flush_updates(session_factory, pending_updates)
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
    parser.add_argument(
        "--count-only",
        action="store_true",
        help="Print how many pending rows still need AI scoring and exit -- no LLM calls.",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.apply, args.limit, args.count_only))


if __name__ == "__main__":
    sys.exit(main())
