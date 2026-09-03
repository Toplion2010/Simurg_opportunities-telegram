import base64
import json
import os

import openai
from pydantic import BaseModel, field_validator
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import Settings
from src.core.enums import Category, RawAudience
from src.core.exceptions import ProcessingError
from src.core.logging import get_logger

logger = get_logger(__name__)

_CATEGORIES = ", ".join(c.value for c in Category)

_SYSTEM_PROMPT_TEMPLATE = """You are an opportunity parser for a Telegram channel aggregator.

Given raw Telegram message text, extract structured fields and return ONLY a JSON object
shaped as {{"opportunities": [ ... ]}}, a list of one or more opportunity objects.

A single message USUALLY describes exactly one opportunity — in that case return a
list with exactly one object. Only split into multiple objects when the message
clearly bundles 2+ genuinely independent programs, each with its own distinct name,
application link/process, and organizer or eligibility (e.g. two unrelated scholarships
from two different universities posted back-to-back). Do NOT split a single program
just because it has multiple tracks, deadlines, or sub-details — those stay one object.
When in doubt, keep it as one object.

Each opportunity object has these fields:
- is_opportunity: true if this is a real, actionable opportunity (scholarship, internship, grant, competition, job, hackathon, fellowship, conference, program, etc.) that a person can apply to or participate in. Set to false for: channel ads, promotional posts, congratulation messages, general news updates, bot announcements, forwarded memes, or anything with no clear application or participation action.
- title: Short, clear title of the opportunity
- category: One of: {categories}
- audience: Target audience for this opportunity. One of exactly: school, university, both, none.
    school = for school pupils only, i.e. grades 1-12 / K-12 (school olympiads, high-school
      competitions, programs restricted to schoolchildren).
    university = ONLY when the text uses an explicit university-level qualifier —
      "university"/"college"/"undergraduate"/"graduate"/"Master's"/"PhD"/"recent graduate"/
      "early-career", or a clearly university-only context (a specific university's program).
      Anchor this strictly on "university student / graduate / early-career" — do NOT widen
      it to open-ended career level. A phrase like "for students and young professionals" is
      still university (students are eligible), NOT none.
    both = broad or ambiguous eligibility, OR eligibility that is simply not stated. In
      particular, an UNQUALIFIED word like "students", "youth", "learners", or "young people"
      — with no school-only or university-only qualifier attached — is ambiguous and MUST be
      both, never university. When you are unsure, choose both — never guess narrowly.
    none = the text EXPLICITLY restricts eligibility away from students entirely (e.g. a
      grant only for established professionals/companies, or a program with a stated
      minimum that excludes all students). "none" means actively excluded, not merely
      "eligibility unstated" — if it's just unstated, use both.
- deadline: Application deadline (date string or description, e.g. "March 20, 2025" or "Rolling")
- eligibility: Who can apply (brief description)
- location: Country/city or "Remote" or "Online"
- cost: "Free", "Paid", funding amount, or stipend details
- organizer: Organization or company name
- duration: Program length (e.g. "3 months", "Summer 2025")
- rewards: Prize, stipend, scholarship amount, or other benefits
- apply_link: Direct application URL
- description: Clean, professional 2-4 sentence summary of the opportunity
- rewritten_text: Full rewritten post in professional, concise English
- card_summary: One complete, self-contained sentence describing the opportunity,
  written to fit in a small image card — MUST be under 130 characters. Never truncate
  mid-word; write it short enough from the start.
- card_eligibility: Short, complete phrase for who can apply, for the same image card —
  MUST be under 90 characters. Prioritize the single most important eligibility fact.
- card_rewards: Short, complete phrase for the prize/reward, for the same image card —
  MUST be under 90 characters.
- additional_links: A list of any http(s) web page URLs mentioned for this opportunity
  beyond its primary apply_link (e.g. an Instagram page, a secondary info page). Never
  drop a link — if a web URL doesn't belong in apply_link, put it here. Do NOT put
  email addresses or phone numbers in this list — those go in extra_notes instead.
- extra_notes: Any other concrete fact about this opportunity that doesn't fit the
  fields above — including contact email addresses and phone numbers (write them as
  plain text, not as links), acceptance rate, sub-track specifics, or caveats
  mentioned in the text. Null if there's nothing left over.
- source_excerpt: A short verbatim quote (1-3 sentences) copied directly from the
  original message text that describes just this opportunity specifically — used later
  as image-generation context. If the message describes only one opportunity, this can
  be a short excerpt of the whole thing.
- min_age: integer age floor, ONLY if explicitly stated ("18+", "ages 18-25"). Null
  otherwise — never infer from education level.

Rules:
- Use null for any field you cannot find in the text
- For audience, when eligibility is broad, unclear, or unstated, default to "both" — only
  narrow to school/university when the text clearly restricts to that group, and only use
  none when students are explicitly excluded
- Category "Job" means a regular paid employment position or vacancy aimed at working
  professionals or general hiring (e.g. "we are hiring a Senior Engineer", "open vacancy",
  "full-time position, 3+ years experience"). Category "Internship" means a student or
  early-career internship, traineeship, or apprenticeship. Distinguish them carefully and
  never label a professional vacancy as an Internship.
- NEVER invent or guess factual data (deadlines, eligibility, rewards)
- Remove marketing hype, emojis that don't add value, and repetitive content
- Keep all important links — every web URL in the source text must end up in exactly
  one opportunity's apply_link or additional_links; every email/phone must end up in
  some opportunity's extra_notes
- description must be factual and based only on provided text
- rewritten_text must be professional, concise, and contain only verified information
- card_summary/card_eligibility/card_rewards must be factual, based only on provided
  text, and respect their character limits — write a short sentence, don't truncate a
  long one
- If is_opportunity is false, all other fields may be null except this still counts
  as one item in the opportunities list
"""


class OpportunityDTO(BaseModel):
    is_opportunity: bool = True
    title: str | None = None
    category: Category | None = None
    audience: RawAudience | None = None

    @field_validator("category", mode="before")
    @classmethod
    def coerce_category(cls, v: object) -> object:
        if v is None:
            return None
        try:
            Category(v)
            return v
        except ValueError:
            return None

    @field_validator("audience", mode="before")
    @classmethod
    def coerce_audience(cls, v: object) -> object:
        if v is None:
            return None
        try:
            RawAudience(v)
            return v
        except ValueError:
            return None
    deadline: str | None = None
    eligibility: str | None = None
    location: str | None = None
    cost: str | None = None
    organizer: str | None = None
    duration: str | None = None
    rewards: str | None = None
    apply_link: str | None = None
    description: str | None = None
    rewritten_text: str | None = None
    card_summary: str | None = None
    card_eligibility: str | None = None
    card_rewards: str | None = None
    additional_links: list[str] = []
    extra_notes: str | None = None
    source_excerpt: str | None = None
    min_age: int | None = None
    # No longer asked of the LLM (removed from the prompt above — it was pure
    # profile-fit judgement and cost prompt tokens). Both fields stay on the
    # model because src/processor/pipeline.py sets them after extraction, from
    # the shared 1-10 rubric in src/core/scoring.py — see that module's
    # docstring for why reachability is now part of the score.
    relevance: int | None = None
    relevance_reason: str | None = None

    @field_validator("additional_links", mode="before")
    @classmethod
    def coerce_additional_links(cls, v: object) -> object:
        return [] if v is None else v

    @field_validator("min_age", mode="before")
    @classmethod
    def validate_min_age(cls, v: object) -> object:
        if v is None:
            return None
        try:
            age = int(v)
        except (TypeError, ValueError):
            return None
        if not (5 <= age <= 99):
            logger.warning("min_age_out_of_range", value=v)
            return None
        return age

    @field_validator("relevance", mode="before")
    @classmethod
    def validate_relevance(cls, v: object) -> object:
        # 1-10, not 1-5 — widened alongside src/core/scoring.py's rubric.
        # Nothing sets this via the LLM anymore, but OpportunityDTO is
        # constructed directly in tests and elsewhere, so the guard stays.
        if v is None:
            return None
        try:
            rating = int(v)
        except (TypeError, ValueError):
            return None
        if not (1 <= rating <= 10):
            logger.warning("relevance_out_of_range", value=v)
            return None
        return rating

    @field_validator("relevance_reason", mode="before")
    @classmethod
    def truncate_relevance_reason(cls, v: object) -> object:
        if v is None:
            return None
        return str(v)[:120]


class ExtractionResult(BaseModel):
    opportunities: list[OpportunityDTO] = []


class FieldExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(categories=_CATEGORIES)

        # Groq client (OpenAI-compatible), built on FIRST USE rather than here.
        #
        # openai.AsyncOpenAI() raises at construction when no api_key is set,
        # and PipelineFactory builds a FieldExtractor unconditionally. That made
        # a Groq key mandatory for every caller that merely *constructs* the
        # pipeline — including the web collector, which supplies already
        # structured DTOs and never calls extract() at all. Deferring the client
        # keeps the key a requirement of using the LLM, not of importing it.
        self._llm_client_instance: openai.AsyncOpenAI | None = None
        self._llm_model = settings.GROQ_MODEL

        # Separate OpenAI client used only for embeddings (optional)
        self._embed_client: openai.AsyncOpenAI | None = None
        if settings.OPENAI_API_KEY:
            self._embed_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    @property
    def _llm_client(self) -> openai.AsyncOpenAI:
        if self._llm_client_instance is None:
            self._llm_client_instance = openai.AsyncOpenAI(
                api_key=self._settings.GROQ_API_KEY,
                base_url=self._settings.GROQ_BASE_URL,
            )
        return self._llm_client_instance

    @retry(
        retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
        # Groq's free tier rate-limits for a full minute at a time, so 3 tries
        # capped at 30s gave up while the window was still open.
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=4, max=90),
        reraise=True,
    )
    async def extract(self, text: str) -> list[OpportunityDTO]:
        try:
            response = await self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2500,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return ExtractionResult.model_validate(data).opportunities
        except (openai.RateLimitError, openai.APIError):
            raise
        except Exception as e:
            logger.exception("extraction_failed", error=str(e))
            raise ProcessingError(f"Field extraction failed: {e}") from e

    async def get_embedding(self, text: str, model: str) -> list[float]:
        if self._embed_client is None:
            raise ProcessingError("OPENAI_API_KEY not set; embeddings unavailable.")
        response = await self._embed_client.embeddings.create(
            model=model,
            input=text[:8000],
        )
        return response.data[0].embedding
