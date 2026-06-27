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

Given raw Telegram message text, extract structured fields and return ONLY a JSON object.

Fields to extract:
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

Rules:
- Use null for any field you cannot find in the text
- NEVER invent or guess factual data (deadlines, eligibility, rewards)
- Remove marketing hype, emojis that don't add value, and repetitive content
- Keep all important links
- description must be factual and based only on provided text
- rewritten_text must be professional, concise, and contain only verified information
- If is_opportunity is false, all other fields may be null
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
    async def extract(self, text: str) -> OpportunityDTO:
        try:
            response = await self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=1500,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return OpportunityDTO.model_validate(data)
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
