"""POST /augment — classify intent, retrieve context, and return an augmented prompt."""

from fastapi import APIRouter, HTTPException

from backend.api.dependencies import get_augment_service
from backend.domain.models import AugmentRequest, AugmentResponse
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/augment", tags=["augment"])


@router.post(
    "",
    response_model=AugmentResponse,
    summary="Classify intent and augment the prompt with Obsidian context",
    responses={
        503: {"description": "Intent classifier or search service not ready"},
    },
)
def augment_prompt(request: AugmentRequest) -> AugmentResponse:
    """Run the full classify → retrieve → format pipeline in a single call.

    - If the message does not require personal context: returns immediately
      with `retrieval_attempted: false` and `augmented_prompt: null`.
    - If personal context is required but no results are found: returns
      `retrieval_attempted: true, context_injected: false`.
    - If results are found: returns `context_injected: true` and a fully
      assembled `augmented_prompt` ready for LLM injection.

    Latency targets: < 60ms (pass-through), < 600ms (retrieval path).
    """
    service = get_augment_service()

    try:
        return service.augment(request)
    except Exception:
        logger.exception("Augmentation failed for message: %.80s", request.message)
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "AUGMENT_UNAVAILABLE",
                "detail": "Augmentation service is temporarily unavailable. "
                "Ensure the index has been built and the embedding model is loaded.",
            },
        )
