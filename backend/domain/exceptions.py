"""Domain exceptions for the Second Brain Interface.

These are raised by application-layer services to signal expected failure
conditions.  Route handlers catch them and map them to appropriate HTTP
responses.  Unexpected exceptions (programming errors, etc.) are left to
propagate to the global exception handler registered in ``main.py``.
"""


class SecondBrainError(Exception):
    """Base class for all Second Brain Interface domain errors."""


class RebuildInProgressError(SecondBrainError):
    """Raised by IndexService when a full rebuild is already running."""


class ServiceUnavailableError(SecondBrainError):
    """Raised when a downstream service (Qdrant, embedding model) is unreachable."""


class NoteNotFoundError(SecondBrainError):
    """Raised when a requested note is not present in the index."""
