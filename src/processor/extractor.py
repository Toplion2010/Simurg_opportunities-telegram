import base64
import json
import os

import openai
from pydantic import BaseModel, field_validator
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import Settings
from src.core.enums import Category
from src.core.exceptions import ProcessingError
from src.core.logging import get_logger

logger = get_logger(__name__)

_CATEGORIES = ", ".join(c.value for c in Category)

_SYSTEM_PROMPT = f"""You are an opportunity parser for a Telegram channel aggregator.

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
- category: One of: {_CATEGORIES}
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

Rules:
- Use null for any field you cannot find in the text
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


class ExtractionResult(BaseModel):
    opportunities: list[OpportunityDTO] = []


class FieldExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        # Groq client (OpenAI-compatible)
        self._llm_client = openai.AsyncOpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url=settings.GROQ_BASE_URL,
        )
        self._llm_model = settings.GROQ_MODEL

        # Separate OpenAI client used only for embeddings (optional)
        self._embed_client: openai.AsyncOpenAI | None = None
        if settings.OPENAI_API_KEY:
            self._embed_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    @retry(
        retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def extract(self, text: str) -> list[OpportunityDTO]:
        try:
            response = await self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
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
