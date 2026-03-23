from fastapi import APIRouter, HTTPException

from backend.config import get_settings
from backend.domain.models import (
    TokenizeRequest,
    TokenizeResponse,
    TokenizeSegmentItem,
    TokenizeTokenItem,
)
from backend.infrastructure.cjk_tokenizer import tokenize_for_sparse_debug

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post(
    "/tokenize",
    response_model=TokenizeResponse,
    summary="Debug CJK sparse tokenization pipeline",
    responses={404: {"description": "Debug endpoints are disabled"}},
)
def debug_tokenize(request: TokenizeRequest) -> TokenizeResponse:
    """Return intermediate tokenization details for troubleshooting."""
    if not get_settings().debug_endpoints:
        raise HTTPException(status_code=404, detail="Not found")

    payload = tokenize_for_sparse_debug(request.text)
    return TokenizeResponse(
        original=payload["original"],
        normalized=payload["normalized"],
        sanitized=payload["sanitized"],
        detected_language=payload["detected_language"],
        segments=[TokenizeSegmentItem(**s) for s in payload["segments"]],
        sparse_output=payload["sparse_output"],
        tokens=[TokenizeTokenItem(**t) for t in payload["tokens"]],
    )
