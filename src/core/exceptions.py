class SimurgError(Exception):
    """Base exception for all Simurg domain errors."""


class DuplicateError(SimurgError):
    """Raised when an opportunity is detected as a duplicate."""


class ProcessingError(SimurgError):
    """Raised when the AI processing pipeline fails."""


class PublishError(SimurgError):
    """Raised when publishing to the destination channel fails."""


class CollectorError(SimurgError):
    """Raised when the Telethon collector encounters an error."""
