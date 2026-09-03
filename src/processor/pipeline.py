from src.core.enums import Audience, Category, OpportunityStatus, RawAudience
from src.core.exceptions import ProcessingError
from src.core.logging import get_logger
from src.core.scoring import infer_cost_amount, infer_is_online
from src.core.scoring import score as reachability_score
from src.db.models.opportunity import Opportunity
from src.db.models.raw_message import RawMessage
from src.db.models.source_channel import SourceChannel
from src.db.repositories.opportunity import OpportunityRepository
from src.db.repositories.raw_message import RawMessageRepository
from src.processor.age import parse_min_age
from src.processor.classifier import CategoryClassifier
from src.processor.cleaner import TextCleaner
from src.processor.deduplicator import Deduplicator
from src.processor.extractor import FieldExtractor, OpportunityDTO
from src.processor.source_link import build_source_url
from src.processor.vision import ImageReader

logger = get_logger(__name__)


class ProcessingPipeline:
    def __init__(
        self,
        cleaner: TextCleaner,
        extractor: FieldExtractor,
        classifier: CategoryClassifier,
        deduplicator: Deduplicator,
        opp_repo: OpportunityRepository,
        raw_repo: RawMessageRepository,
        image_reader: ImageReader,
    ) -> None:
        self._cleaner = cleaner
        self._extractor = extractor
        self._classifier = classifier
        self._deduplicator = deduplicator
        self._opp_repo = opp_repo
        self._raw_repo = raw_repo
        self._image_reader = image_reader

    async def run(
        self,
        raw: RawMessage,
        media_path: str | None = None,
        source_channel: SourceChannel | None = None,
        dtos: list[OpportunityDTO] | None = None,
        source_url: str | None = None,
    ) -> list[Opportunity]:
        """Turn one raw item into Opportunity rows.

        ``dtos`` lets a caller supply already-structured fields and SKIP the LLM
        extractor entirely. The web collector uses this: its catalogs expose
        JSON-LD and a REST API, so an extraction call would spend Groq's
        free-tier budget re-deriving fields we were handed. Everything after
        extraction — classification, the Job drop, the audience default, the age
        gate, dedup, the row build — is shared by both paths on purpose, so a
        scraped opportunity is governed by exactly the same rules as a
        Telegram one.

        ``source_url`` overrides the t.me permalink for sources that have their
        own canonical page.
        """
        if dtos is None and not raw.text:
            return []

        if source_url is None:
            source_url = build_source_url(source_channel, raw.telegram_msg_id)

        source_label = None
        if source_channel is not None:
            source_label = source_channel.identifier or source_channel.username

        results: list[Opportunity] = []
        try:
            if dtos is None:
                clean_text = self._cleaner.clean(raw.text)

                # Read any attached poster image so facts shown only on the image
                # (prize amounts, deadlines, eligibility) reach the extractor too.
                extraction_input = clean_text
                if media_path:
                    image_text = await self._image_reader.read(media_path)
                    if image_text:
                        extraction_input = (
                            f"{clean_text}\n\n"
                            "[Text and details read from the post's attached poster image "
                            "(treat these as facts too — the caption may omit them):]\n"
                            f"{image_text}"
                        )
                        logger.info("image_text_extracted", raw_id=raw.id, chars=len(image_text))

                dtos = await self._extractor.extract(extraction_input)
            else:
                # Pre-structured input. The age gate below still needs a text
                # blob to regex over; the DTO's own fields are all we have.
                extraction_input = raw.text or ""

            for dto in dtos:
                if not dto.is_opportunity:
                    logger.info("not_an_opportunity_skipped", raw_id=raw.id)
                    continue

                dto.category = self._classifier.classify(dto, extraction_input)

                # Regular job vacancies (not student internships) are out of scope for
                # this students' channel — drop them before a row is ever created.
                if dto.category == Category.Job:
                    logger.info("job_skipped", raw_id=raw.id, title=dto.title)
                    continue

                # Web-sourced dtos already carry a relevance from to_dto.py,
                # computed from the item's REAL is_online/cost_amount fields
                # — higher fidelity than anything derivable from free text, so
                # it is never overwritten here. Only Telegram dtos (no
                # structured fields to begin with) reach this branch.
                if dto.relevance is None:
                    is_online = infer_is_online(dto.location)
                    cost_amount = infer_cost_amount(dto.cost)
                    score_text = " ".join(
                        filter(None, [dto.title, dto.description, dto.eligibility, dto.organizer])
                    )
                    dto.relevance, dto.relevance_reason = reachability_score(
                        is_online, cost_amount, dto.location, score_text
                    )

                # null/invalid -> both. No keyword guessing: "students" alone is too
                # ambiguous (school vs university) to classify by keyword.
                audience = dto.audience or RawAudience.both
                if audience == RawAudience.none:
                    logger.info("audience_none_skipped", raw_id=raw.id)
                    continue

                # Age gate: nothing 18+ may reach the school channel. Combine the
                # LLM's explicit reading with a regex parser over the full source
                # text — whichever is stricter (higher) wins.
                age_sources = " ".join(
                    filter(
                        None,
                        [dto.title, dto.description, dto.eligibility, extraction_input],
                    )
                )
                parsed_min_age = parse_min_age(age_sources)
                min_age = max(
                    (age for age in (dto.min_age, parsed_min_age) if age is not None),
                    default=None,
                )
                if min_age is not None and min_age >= 18 and audience in (
                    RawAudience.both,
                    RawAudience.school,
                ):
                    logger.info(
                        "age_gate_applied",
                        raw_id=raw.id,
                        min_age=min_age,
                        old_audience=audience.value,
                        new_audience=RawAudience.university.value,
                    )
                    audience = RawAudience.university

                hash_key = self._deduplicator.make_hash(dto)
                if await self._deduplicator.check(dto, self._opp_repo):
                    # Logged because this `continue` is the ONLY place
                    # cross-source overlap is observable. Without it there is no
                    # way to answer "what does a new source actually add that
                    # the other 40 didn't", which is the stop rule for keeping
                    # a source at all (PLAN_SOURCE_AUDIT.md:227-232).
                    logger.info(
                        "duplicate_skipped",
                        raw_id=raw.id,
                        title=dto.title,
                        hash=hash_key,
                        source=source_label,
                    )
                    continue

                opp = Opportunity(
                    raw_message_id=raw.id,
                    title=dto.title,
                    category=dto.category,
                    audience=Audience(audience.value),  # safe: 'none' already filtered out above
                    deadline=dto.deadline,
                    eligibility=dto.eligibility,
                    location=dto.location,
                    cost=dto.cost,
                    organizer=dto.organizer,
                    duration=dto.duration,
                    rewards=dto.rewards,
                    apply_link=dto.apply_link,
                    description=dto.description,
                    rewritten_text=dto.rewritten_text,
                    card_summary=dto.card_summary,
                    card_eligibility=dto.card_eligibility,
                    card_rewards=dto.card_rewards,
                    additional_links=dto.additional_links,
                    extra_notes=dto.extra_notes,
                    source_excerpt=dto.source_excerpt,
                    min_age=min_age,
                    relevance=dto.relevance,
                    relevance_reason=dto.relevance_reason,
                    source_url=source_url,
                    similarity_hash=hash_key,
                    media_path=media_path,
                    hooks=[],
                    status=OpportunityStatus.pending,
                )
                await self._opp_repo.save(opp)
                await self._deduplicator.store(dto)
                logger.info("opportunity_created", opp_id=opp.id, title=opp.title)
                results.append(opp)

            raw.processed = True
            return results

        except ProcessingError:
            logger.exception("processing_error", raw_id=raw.id)
            return results
