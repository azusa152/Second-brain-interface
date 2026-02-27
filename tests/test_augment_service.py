"""Unit tests for AugmentService: pipeline logic, context formatting, and prompt assembly."""

from unittest.mock import MagicMock

import pytest

from backend.application.augment_service import (
    AugmentService,
    assemble_augmented_prompt,
    escape_xml_attr,
    escape_xml_text,
    format_context_block,
)
from backend.domain.constants import AUGMENT_CONTEXT_MAX_CHARS, AUGMENT_TOP_K_DEFAULT
from backend.domain.models import (
    AugmentRequest,
    ContextBlock,
    IntentClassification,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    note_path: str = "notes/foo.md",
    note_title: str = "Foo",
    content: str = "Some content about the topic.",
    score: float = 0.85,
    heading_context: str | None = "Background",
) -> SearchResultItem:
    return SearchResultItem(
        chunk_id=f"{note_path}::0",
        note_path=note_path,
        note_title=note_title,
        content=content,
        score=score,
        heading_context=heading_context,
    )


def _classification(
    requires: bool = True,
    confidence: float = 0.75,
    suggested_query: str | None = "investment portfolio 2024",
) -> IntentClassification:
    return IntentClassification(
        requires_personal_context=requires,
        confidence=confidence,
        triggered_signals=["keyword:investment", "temporal:2024"] if requires else [],
        suggested_query=suggested_query if requires else None,
    )


def _search_response(results: list[SearchResultItem], time_ms: float = 42.0) -> SearchResponse:
    return SearchResponse(
        query="investment portfolio 2024",
        results=results,
        related_notes=[],
        total_hits=len(results),
        search_time_ms=time_ms,
    )


def _make_service(
    intent_result: IntentClassification | None = None,
    search_results: list[SearchResultItem] | None = None,
) -> AugmentService:
    mock_intent = MagicMock()
    mock_intent.classify.return_value = intent_result or _classification()

    mock_search = MagicMock()
    results = [_make_result()] if search_results is None else search_results
    mock_search.search.return_value = _search_response(results)

    return AugmentService(intent_service=mock_intent, search_service=mock_search)


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

class TestXmlEscaping:
    def test_escape_attr_ampersand(self) -> None:
        assert escape_xml_attr("a&b") == "a&amp;b"

    def test_escape_attr_lt_gt(self) -> None:
        assert escape_xml_attr("<tag>") == "&lt;tag&gt;"

    def test_escape_attr_double_quote(self) -> None:
        assert escape_xml_attr('say "hello"') == "say &quot;hello&quot;"

    def test_escape_text_preserves_double_quote(self) -> None:
        assert escape_xml_text('say "hello"') == 'say "hello"'

    def test_escape_text_ampersand_and_brackets(self) -> None:
        assert escape_xml_text("a<b>&c") == "a&lt;b&gt;&amp;c"

    def test_no_special_chars_unchanged(self) -> None:
        assert escape_xml_attr("plain text") == "plain text"
        assert escape_xml_text("plain text") == "plain text"


# ---------------------------------------------------------------------------
# Pipeline: general query (no retrieval)
# ---------------------------------------------------------------------------

class TestAugmentPipelineNoRetrieval:
    def test_general_query_skips_retrieval(self) -> None:
        svc = _make_service(intent_result=_classification(requires=False, confidence=0.1))
        result = svc.augment(AugmentRequest(message="what is recursion?"))

        assert result.retrieval_attempted is False
        assert result.context_injected is False
        assert result.augmented_prompt is None
        assert result.context_block is None
        assert result.search_time_ms is None

    def test_general_query_forwards_intent_metadata(self) -> None:
        svc = _make_service(intent_result=_classification(requires=False, confidence=0.08))
        result = svc.augment(AugmentRequest(message="what is a linked list?"))

        assert result.intent_confidence == pytest.approx(0.08)
        assert result.triggered_signals == []

    def test_search_not_called_for_general_query(self) -> None:
        mock_search = MagicMock()
        mock_intent = MagicMock()
        mock_intent.classify.return_value = _classification(requires=False)
        svc = AugmentService(intent_service=mock_intent, search_service=mock_search)

        svc.augment(AugmentRequest(message="how does hashing work?"))

        mock_search.search.assert_not_called()


# ---------------------------------------------------------------------------
# Pipeline: personal query with results
# ---------------------------------------------------------------------------

class TestAugmentPipelineWithContext:
    def test_personal_query_with_results_injects_context(self) -> None:
        svc = _make_service()
        result = svc.augment(AugmentRequest(message="my investment portfolio last year"))

        assert result.retrieval_attempted is True
        assert result.context_injected is True
        assert result.augmented_prompt is not None
        assert result.context_block is not None

    def test_uses_suggested_query_for_search(self) -> None:
        mock_intent = MagicMock()
        mock_intent.classify.return_value = _classification(suggested_query="clean search query")
        mock_search = MagicMock()
        mock_search.search.return_value = _search_response([_make_result()])
        svc = AugmentService(intent_service=mock_intent, search_service=mock_search)

        svc.augment(AugmentRequest(message="can you tell me about my investment portfolio"))

        call_args: SearchRequest = mock_search.search.call_args[0][0]
        assert call_args.query == "clean search query"

    def test_falls_back_to_original_message_when_no_suggested_query(self) -> None:
        original = "my investment portfolio last year"
        mock_intent = MagicMock()
        mock_intent.classify.return_value = _classification(suggested_query=None)
        mock_search = MagicMock()
        mock_search.search.return_value = _search_response([_make_result()])
        svc = AugmentService(intent_service=mock_intent, search_service=mock_search)

        svc.augment(AugmentRequest(message=original))

        call_args: SearchRequest = mock_search.search.call_args[0][0]
        assert call_args.query == original

    def test_search_request_disables_graph_enrichment(self) -> None:
        """include_related must be False to avoid unnecessary Qdrant link queries."""
        mock_intent = MagicMock()
        mock_intent.classify.return_value = _classification()
        mock_search = MagicMock()
        mock_search.search.return_value = _search_response([_make_result()])
        svc = AugmentService(intent_service=mock_intent, search_service=mock_search)

        svc.augment(AugmentRequest(message="my investment portfolio"))

        call_args: SearchRequest = mock_search.search.call_args[0][0]
        assert call_args.include_related is False

    def test_top_k_forwarded_to_search(self) -> None:
        mock_intent = MagicMock()
        mock_intent.classify.return_value = _classification()
        mock_search = MagicMock()
        mock_search.search.return_value = _search_response([_make_result()])
        svc = AugmentService(intent_service=mock_intent, search_service=mock_search)

        svc.augment(AugmentRequest(message="my notes", top_k=7))

        call_args: SearchRequest = mock_search.search.call_args[0][0]
        assert call_args.top_k == 7

    def test_default_top_k_matches_constant(self) -> None:
        req = AugmentRequest(message="my notes")
        assert req.top_k == AUGMENT_TOP_K_DEFAULT

    def test_search_time_ms_propagated(self) -> None:
        mock_intent = MagicMock()
        mock_intent.classify.return_value = _classification()
        mock_search = MagicMock()
        mock_search.search.return_value = _search_response([_make_result()], time_ms=99.5)
        svc = AugmentService(intent_service=mock_intent, search_service=mock_search)

        result = svc.augment(AugmentRequest(message="my notes"))

        assert result.search_time_ms == pytest.approx(99.5)


# ---------------------------------------------------------------------------
# Pipeline: personal query with no results
# ---------------------------------------------------------------------------

class TestAugmentPipelineNoResults:
    def test_no_results_sets_retrieval_attempted_true(self) -> None:
        svc = _make_service(search_results=[])
        result = svc.augment(AugmentRequest(message="my obscure portfolio note"))

        assert result.retrieval_attempted is True
        assert result.context_injected is False
        assert result.augmented_prompt is None
        assert result.context_block is None

    def test_no_results_preserves_intent_metadata(self) -> None:
        svc = _make_service(
            intent_result=_classification(confidence=0.72),
            search_results=[],
        )
        result = svc.augment(AugmentRequest(message="my obscure note"))

        assert result.intent_confidence == pytest.approx(0.72)
        assert "keyword:investment" in result.triggered_signals


# ---------------------------------------------------------------------------
# _format_context_block
# ---------------------------------------------------------------------------

class TestFormatContextBlock:
    def test_xml_structure_is_valid(self) -> None:
        block = format_context_block([_make_result()], include_sources=True)

        assert block.xml_content.startswith("<context>")
        assert block.xml_content.endswith("</context>")
        assert "<note " in block.xml_content
        assert "</note>" in block.xml_content

    def test_note_attributes_present(self) -> None:
        result = _make_result(note_title="My Note", note_path="notes/my.md", score=0.92)
        block = format_context_block([result], include_sources=True)

        assert 'title="My Note"' in block.xml_content
        assert 'path="notes/my.md"' in block.xml_content
        assert 'score="0.92"' in block.xml_content

    def test_content_appears_in_xml(self) -> None:
        result = _make_result(content="important financial decision")
        block = format_context_block([result], include_sources=True)

        assert "important financial decision" in block.xml_content

    def test_sources_populated_when_requested(self) -> None:
        results = [
            _make_result(note_path="a.md", note_title="A"),
            _make_result(note_path="b.md", note_title="B"),
        ]
        block = format_context_block(results, include_sources=True)

        assert len(block.sources) == 2
        assert block.sources[0].note_path == "a.md"
        assert block.sources[1].note_path == "b.md"

    def test_sources_empty_when_not_requested(self) -> None:
        block = format_context_block([_make_result()], include_sources=False)

        assert block.sources == []

    def test_total_chars_counts_escaped_content(self) -> None:
        block = format_context_block([_make_result(content="x" * 100)], include_sources=False)
        assert block.total_chars == 100

    def test_total_chars_includes_escape_overhead(self) -> None:
        """Content with '&' expands to '&amp;' — total_chars must reflect that."""
        block = format_context_block([_make_result(content="a&b")], include_sources=False)
        assert block.total_chars == len("a&amp;b")

    def test_oversized_note_dropped_entirely(self) -> None:
        """A single note larger than the budget is dropped, not truncated."""
        content = "x" * (AUGMENT_CONTEXT_MAX_CHARS + 500)
        block = format_context_block([_make_result(content=content)], include_sources=False)

        assert block.total_chars == 0
        assert block.xml_content.count("<note ") == 0

    def test_second_note_dropped_when_budget_exhausted(self) -> None:
        first = _make_result(note_path="a.md", content="x" * AUGMENT_CONTEXT_MAX_CHARS)
        second = _make_result(note_path="b.md", content="extra content")
        block = format_context_block([first, second], include_sources=True)

        assert block.xml_content.count("<note ") == 1
        assert "b.md" not in block.xml_content
        assert len(block.sources) == 1

    def test_multiple_notes_fit_within_budget(self) -> None:
        """Several shorter notes should all be included when they fit."""
        a = _make_result(note_path="a.md", note_title="A", content="aaa")
        b = _make_result(note_path="b.md", note_title="B", content="bbb")
        c = _make_result(note_path="c.md", note_title="C", content="ccc")
        block = format_context_block([a, b, c], include_sources=True)

        assert block.xml_content.count("<note ") == 3
        assert len(block.sources) == 3
        assert block.total_chars == 9  # 3 + 3 + 3

    def test_xml_escaping_in_title_and_path(self) -> None:
        result = _make_result(note_title='Note <"special">', note_path="notes/a&b.md")
        block = format_context_block([result], include_sources=False)

        assert "Note <" not in block.xml_content
        assert "&lt;" in block.xml_content
        assert "&amp;" in block.xml_content

    def test_xml_escaping_in_content(self) -> None:
        result = _make_result(content="a < b && c > d")
        block = format_context_block([result], include_sources=False)

        assert "a < b" not in block.xml_content
        assert "&lt;" in block.xml_content
        assert "&amp;" in block.xml_content

    def test_source_score_rounded_to_4_decimals(self) -> None:
        result = _make_result(score=0.876543210)
        block = format_context_block([result], include_sources=True)

        assert block.sources[0].score == round(0.876543210, 4)

    def test_heading_context_preserved_in_source(self) -> None:
        result = _make_result(heading_context="Decision")
        block = format_context_block([result], include_sources=True)

        assert block.sources[0].heading_context == "Decision"

    def test_none_heading_context_preserved_in_source(self) -> None:
        result = _make_result(heading_context=None)
        block = format_context_block([result], include_sources=True)

        assert block.sources[0].heading_context is None


# ---------------------------------------------------------------------------
# _assemble_augmented_prompt
# ---------------------------------------------------------------------------

class TestAssembleAugmentedPrompt:
    def _make_block(self, xml: str = "<context>\n  <note score='0.9'>text</note>\n</context>") -> ContextBlock:
        return ContextBlock(xml_content=xml, sources=[], total_chars=4)

    def test_prompt_contains_system_header(self) -> None:
        prompt = assemble_augmented_prompt("hello", self._make_block())

        assert "[System:" in prompt

    def test_prompt_contains_context_xml(self) -> None:
        xml = "<context>\n  <note score='0.9'>my text</note>\n</context>"
        prompt = assemble_augmented_prompt("hello", self._make_block(xml))

        assert xml in prompt

    def test_prompt_contains_instruction_block(self) -> None:
        prompt = assemble_augmented_prompt("hello", self._make_block())

        assert "<instruction>" in prompt
        assert "</instruction>" in prompt
        assert "Based on your Obsidian notes" in prompt

    def test_prompt_ends_with_user_message(self) -> None:
        message = "What was my investment plan for 2024?"
        prompt = assemble_augmented_prompt(message, self._make_block())

        assert prompt.endswith(f"[User]: {message}")

    def test_prompt_order_system_context_instruction_user(self) -> None:
        prompt = assemble_augmented_prompt("my question", self._make_block())

        system_pos = prompt.index("[System:")
        context_pos = prompt.index("<context>")
        instruction_pos = prompt.index("<instruction>")
        user_pos = prompt.index("[User]:")

        assert system_pos < context_pos < instruction_pos < user_pos
