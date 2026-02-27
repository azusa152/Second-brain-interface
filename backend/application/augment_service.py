"""Context augmentation service.

Implements the full classify → retrieve → format pipeline:
  1. Classify the user message with IntentService.
  2. If personal context is required, search the vault with SearchService.
  3. Format results into an XML context block.
  4. Assemble an augmented prompt ready for LLM injection.
"""

from backend.application.intent_service import IntentService
from backend.application.search_service import SearchService
from backend.domain.constants import AUGMENT_CONTEXT_MAX_CHARS
from backend.domain.models import (
    AugmentRequest,
    AugmentResponse,
    ContextBlock,
    IntentClassification,
    SearchRequest,
    SearchResultItem,
    SourceCitation,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)

# Fixed prompt fragments — defined once at module level so they appear in the
# same place for easy modification, and are not re-constructed on every call.
_SYSTEM_HEADER = (
    "[System: The following context was retrieved from the user's Obsidian knowledge base]"
)
_INSTRUCTION_BLOCK = (
    "<instruction>\n"
    "  If the context above is relevant to the question, begin your response with "
    '"Based on your Obsidian notes..." and cite specific note titles.\n'
    "  If the context is not relevant to the question, ignore it and respond normally "
    "without mentioning it.\n"
    "</instruction>"
)


def escape_xml_attr(text: str) -> str:
    """Escape characters that are special inside XML attribute values."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def escape_xml_text(text: str) -> str:
    """Escape characters that are special inside XML element content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_response(
    classification: IntentClassification,
    *,
    retrieval_attempted: bool,
    context_injected: bool,
    context_block: ContextBlock | None = None,
    augmented_prompt: str | None = None,
    search_time_ms: float | None = None,
) -> AugmentResponse:
    """Build an AugmentResponse, centralising the fields shared by all exit paths."""
    return AugmentResponse(
        retrieval_attempted=retrieval_attempted,
        context_injected=context_injected,
        intent_confidence=classification.confidence,
        triggered_signals=classification.triggered_signals,
        context_block=context_block,
        augmented_prompt=augmented_prompt,
        search_time_ms=search_time_ms,
    )


class AugmentService:
    """Orchestrate the classify → retrieve → format augmentation pipeline."""

    def __init__(
        self,
        intent_service: IntentService,
        search_service: SearchService,
    ) -> None:
        self._intent_service = intent_service
        self._search_service = search_service

    def augment(self, request: AugmentRequest) -> AugmentResponse:
        """Run the full pipeline and return a structured augmentation response.

        Fast path (< 60ms): when intent classification returns
        requires_personal_context=False, no search or formatting is performed.

        Retrieval path (< 600ms): searches the vault, formats a context block,
        and assembles the augmented prompt.
        """
        classification = self._intent_service.classify(request.message)

        if not classification.requires_personal_context:
            logger.debug(
                "Augment: no personal context needed (confidence=%.3f)",
                classification.confidence,
            )
            return _build_response(
                classification,
                retrieval_attempted=False,
                context_injected=False,
            )

        query = classification.suggested_query or request.message
        search_resp = self._search_service.search(
            SearchRequest(
                query=query,
                top_k=request.top_k,
                include_related=False,
            )
        )

        if not search_resp.results:
            logger.debug("Augment: retrieval attempted but no results for query '%s'", query)
            return _build_response(
                classification,
                retrieval_attempted=True,
                context_injected=False,
                search_time_ms=search_resp.search_time_ms,
            )

        context_block = format_context_block(
            search_resp.results,
            include_sources=request.include_sources,
        )
        augmented_prompt = assemble_augmented_prompt(request.message, context_block)

        logger.debug(
            "Augment: injected %d notes (%d chars) for query '%s'",
            len(context_block.sources),
            context_block.total_chars,
            query,
        )

        return _build_response(
            classification,
            retrieval_attempted=True,
            context_injected=True,
            context_block=context_block,
            augmented_prompt=augmented_prompt,
            search_time_ms=search_resp.search_time_ms,
        )


def format_context_block(
    results: list[SearchResultItem],
    include_sources: bool,
) -> ContextBlock:
    """Format search results into an XML context block.

    Notes are included in order while their escaped content fits within
    AUGMENT_CONTEXT_MAX_CHARS. A note whose escaped content would exceed
    the remaining budget is skipped entirely (not truncated mid-sentence)
    to produce cleaner context for the LLM. Budget tracking uses the
    escaped length so ``total_chars`` always matches what is actually
    placed inside the ``<context>`` element.
    """
    sources: list[SourceCitation] = []
    note_xml_parts: list[str] = []
    chars_used = 0

    for result in results:
        if chars_used >= AUGMENT_CONTEXT_MAX_CHARS:
            break

        escaped_content = escape_xml_text(result.content)
        remaining = AUGMENT_CONTEXT_MAX_CHARS - chars_used

        if len(escaped_content) > remaining:
            break

        chars_used += len(escaped_content)

        note_xml_parts.append(
            f'  <note title="{escape_xml_attr(result.note_title)}" '
            f'path="{escape_xml_attr(result.note_path)}" '
            f'score="{result.score:.2f}">\n'
            f"    {escaped_content}\n"
            f"  </note>"
        )

        if include_sources:
            sources.append(
                SourceCitation(
                    note_path=result.note_path,
                    note_title=result.note_title,
                    heading_context=result.heading_context,
                    score=round(result.score, 4),
                )
            )

    xml_content = "<context>\n" + "\n".join(note_xml_parts) + "\n</context>"
    return ContextBlock(xml_content=xml_content, sources=sources, total_chars=chars_used)


def assemble_augmented_prompt(
    original_message: str,
    context_block: ContextBlock,
) -> str:
    """Combine system header, context XML, instruction block, and user message."""
    return (
        f"{_SYSTEM_HEADER}\n"
        f"{context_block.xml_content}\n"
        f"{_INSTRUCTION_BLOCK}\n"
        f"\n"
        f"[User]: {original_message}"
    )
