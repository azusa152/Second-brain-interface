"""Intent classification service.

Owns the domain anchor configuration, pre-warms anchor embeddings once at startup,
and orchestrates the IntentClassifier to return a structured IntentClassification.
"""

import threading

from backend.domain.constants import (
    INTENT_DEFAULT_DOMAIN_ANCHORS,
    INTENT_DEFAULT_KEYWORDS,
    INTENT_THRESHOLD,
)
from backend.domain.models import IntentClassification
from backend.infrastructure.embedding import EmbeddingService
from backend.infrastructure.intent_classifier import (
    IntentClassifier,
    composite_score,
    strip_politeness_prefix,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)


class IntentService:
    """Orchestrate intent classification for a user message.

    warm_up() must be called once at application startup (from initialize_services())
    to pre-compute anchor embeddings. This guarantees the 50ms latency target on
    every request by avoiding on-demand model inference for the anchors.
    """

    def __init__(
        self,
        embedder: EmbeddingService,
        keywords: list[str] | None = None,
        domain_anchors: list[str] | None = None,
    ) -> None:
        self._embedder = embedder
        self._keywords = keywords or list(INTENT_DEFAULT_KEYWORDS)
        self._domain_anchors = domain_anchors or list(INTENT_DEFAULT_DOMAIN_ANCHORS)
        self._anchor_embeddings: list[list[float]] = []
        self._warm_up_lock = threading.Lock()
        self._classifier = IntentClassifier(keywords=self._keywords)

    def warm_up(self) -> None:
        """Pre-compute anchor embeddings (~100ms one-time cost at startup).

        Thread-safe and idempotent: if two threads race, only the first performs
        the embedding; the second exits immediately after acquiring the lock.
        """
        # Fast path: already warmed up, no lock needed.
        if self._anchor_embeddings:
            return
        with self._warm_up_lock:
            # Re-check under lock in case another thread completed warm-up
            # between the fast-path check and acquiring the lock.
            if self._anchor_embeddings:
                return
            logger.info(
                "Warming up intent classifier: embedding %d domain anchors",
                len(self._domain_anchors),
            )
            self._anchor_embeddings = self._embedder.embed_batch(self._domain_anchors)
            logger.info("Intent classifier warm-up complete")

    def classify(self, message: str) -> IntentClassification:
        """Classify a user message and return a structured result.

        If warm_up() has not been called, anchor embeddings are empty and the
        semantic signal contributes 0. The classifier still works via keyword
        and temporal signals.
        """
        if not self._anchor_embeddings:
            logger.warning(
                "Intent classifier: anchor embeddings not warmed up; "
                "semantic signal will be zero"
            )

        query_embedding = self._embedder.embed_text(message)

        signals = self._classifier.classify(
            message=message,
            query_embedding=query_embedding,
            anchor_embeddings=self._anchor_embeddings,
            anchor_labels=self._domain_anchors,
        )

        confidence = round(composite_score(signals), 4)
        requires_personal_context = confidence >= INTENT_THRESHOLD

        suggested_query: str | None = None
        if requires_personal_context:
            stripped = strip_politeness_prefix(message)
            suggested_query = stripped if stripped else message

        return IntentClassification(
            requires_personal_context=requires_personal_context,
            confidence=confidence,
            triggered_signals=list(signals.triggered),
            suggested_query=suggested_query,
        )
