"""POST /intent/classify — classify whether a message requires personal knowledge retrieval."""

from fastapi import APIRouter, HTTPException

from backend.api.dependencies import get_intent_service
from backend.domain.models import IntentClassification, IntentRequest
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/intent", tags=["intent"])


@router.post(
    "/classify",
    response_model=IntentClassification,
    summary="Classify whether a message requires personal Obsidian knowledge",
    responses={
        503: {"description": "Embedding service not ready"},
    },
)
def classify_intent(request: IntentRequest) -> IntentClassification:
    """Classify a user message using keyword, semantic, and temporal signals.

    Returns a structured result indicating whether personal context retrieval
    is recommended, along with the composite confidence score and which
    signals fired.

    Latency target: < 50ms (anchor embeddings are pre-warmed at startup).
    """
    service = get_intent_service()

    try:
        return service.classify(request.message)
    except Exception:
        logger.exception("Intent classification failed for message: %.80s", request.message)
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "INTENT_CLASSIFIER_UNAVAILABLE",
                "detail": "Intent classification is temporarily unavailable.",
            },
        )
