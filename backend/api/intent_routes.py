"""POST /intent/classify — classify whether a message requires personal knowledge retrieval."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_intent_service
from backend.application.intent_service import IntentService
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
def classify_intent(
    request: IntentRequest,
    service: Annotated[IntentService, Depends(get_intent_service)],
) -> IntentClassification:
    """Classify a user message using keyword, semantic, and temporal signals.

    Returns a structured result indicating whether personal context retrieval
    is recommended, along with the composite confidence score and which
    signals fired.

    Latency target: < 50ms (anchor embeddings are pre-warmed at startup).
    """
    try:
        return service.classify(request.message)
    except Exception as err:
        logger.exception("Intent classification failed for message: %.80s", request.message)
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "INTENT_CLASSIFIER_UNAVAILABLE",
                "message": "Intent classification is temporarily unavailable.",
            },
        ) from err
