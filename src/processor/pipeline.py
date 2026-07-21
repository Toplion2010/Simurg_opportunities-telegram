from src.core.enums import OpportunityStatus
from src.core.exceptions import ProcessingError
from src.core.logging import get_logger
from src.db.models.opportunity import Opportunity
from src.db.models.raw_message import RawMessage
from src.db.repositories.opportunity import OpportunityRepository
from src.db.repositories.raw_message import RawMessageRepository
from src.processor.classifier import CategoryClassifier
from src.processor.cleaner import TextCleaner
from src.processor.deduplicator import Deduplicator
from src.processor.extractor import FieldExtractor

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
    ) -> None:
        self._cleaner = cleaner
        self._extractor = extractor
        self._classifier = classifier
        self._deduplicator = deduplicator
        self._opp_repo = opp_repo
        self._raw_repo = raw_repo

    async def run(self, raw: RawMessage, media_path: str | None = None) -> list[Opportunity]:
        if not raw.text:
            return []

        results: list[Opportunity] = []
        try:
            clean_text = self._cleaner.clean(raw.text)
            dtos = await self._extractor.extract(clean_text)

            for dto in dtos:
                if not dto.is_opportunity:
                    logger.info("not_an_opportunity_skipped", raw_id=raw.id)
                    continue

                dto.category = self._classifier.classify(dto, clean_text)

                if await self._deduplicator.check(dto):
                    continue

                hash_key = self._deduplicator.make_hash(dto)
                opp = Opportunity(
                    raw_message_id=raw.id,
                    title=dto.title,
                    category=dto.category,
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
