from src.core.enums import Category
from src.core.logging import get_logger
from src.processor.extractor import OpportunityDTO

logger = get_logger(__name__)

_KEYWORD_MAP: dict[str, Category] = {
    "intern": Category.Internship,
    "scholar": Category.Scholarship,
    "fellowship": Category.Fellowship,
    "research": Category.Research,
    "competition": Category.Competition,
    "olympiad": Category.Olympiad,
    "hackathon": Category.Hackathon,
    "startup": Category.Startup,
    "accelerat": Category.Accelerator,
    "incubat": Category.Incubator,
    "grant": Category.Grant,
    "conference": Category.Conference,
    "summer program": Category.SummerProgram,
    "summer school": Category.SummerProgram,
    "exchange": Category.Exchange,
    "volunteer": Category.Volunteer,
    "job": Category.Job,
    "hiring": Category.Job,
    "position": Category.Job,
}


class CategoryClassifier:
    def classify(self, dto: OpportunityDTO, original_text: str = "") -> Category | None:
        if dto.category is not None:
            return dto.category

        combined = " ".join(filter(None, [
            dto.title, dto.description, original_text
        ])).lower()

        for keyword, category in _KEYWORD_MAP.items():
            if keyword in combined:
                logger.debug("category_keyword_match", keyword=keyword, category=category)
                return category

        return None
