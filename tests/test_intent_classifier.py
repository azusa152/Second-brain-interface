"""Unit tests for IntentClassifier, IntentService, and the /intent/classify endpoint."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient  # used via conftest client fixture

from backend.application.intent_service import IntentService
from backend.domain.constants import (
    INTENT_RULE_WEIGHT,
    INTENT_SEMANTIC_WEIGHT,
    INTENT_TEMPORAL_WEIGHT,
    INTENT_THRESHOLD,
)
from backend.domain.models import IntentClassification
from backend.infrastructure.intent_classifier import (
    ClassifierSignals,
    IntentClassifier,
    composite_score,
    cosine_similarity,
    strip_politeness_prefix,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEYWORDS = ["investment", "portfolio", "career", "meeting notes", "my decision"]
_ANCHORS = ["personal finance investment", "career planning"]
_ANCHOR_LABELS = ["finance", "career"]

# Unit embedding vectors aligned with anchors (same dimension, unit-normalised is fine)
_ZERO_EMBED: list[float] = [0.0] * 4
_FINANCE_EMBED: list[float] = [1.0, 0.0, 0.0, 0.0]   # max-sim with finance anchor
_UNRELATED_EMBED: list[float] = [0.0, 0.0, 0.0, 1.0]  # low sim with all anchors


def _make_classifier(keywords: list[str] | None = None) -> IntentClassifier:
    return IntentClassifier(keywords=keywords or _KEYWORDS)


def _make_signals(
    rule: float = 0.0,
    semantic: float = 0.0,
    temporal: float = 0.0,
    triggered: tuple[str, ...] = (),
) -> ClassifierSignals:
    return ClassifierSignals(
        rule_score=rule,
        semantic_score=semantic,
        temporal_score=temporal,
        triggered=triggered,
    )


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors_return_one(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_return_zero(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_return_minus_one(self) -> None:
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert cosine_similarity([1.0, 0.0], [0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# strip_politeness_prefix
# ---------------------------------------------------------------------------

class TestStripPolitenessPrefix:
    @pytest.mark.parametrize("prefix,remainder", [
        ("can you tell me what was my investment return", "what was my investment return"),
        ("please find my career notes", "my career notes"),
        ("could you tell me about my portfolio", "about my portfolio"),
        ("I'd like to know my goals", "my goals"),
        ("tell me about my journal", "my journal"),
    ])
    def test_strips_known_prefixes(self, prefix: str, remainder: str) -> None:
        assert strip_politeness_prefix(prefix) == remainder

    def test_does_not_strip_unknown_prefix(self) -> None:
        msg = "What was my investment return last year?"
        assert strip_politeness_prefix(msg) == msg

    def test_case_insensitive(self) -> None:
        assert strip_politeness_prefix("PLEASE FIND my notes") == "my notes"

    def test_empty_string_returns_empty(self) -> None:
        assert strip_politeness_prefix("") == ""


# ---------------------------------------------------------------------------
# Keyword Signal
# ---------------------------------------------------------------------------

class TestKeywordSignal:
    def test_no_keywords_score_zero(self) -> None:
        clf = _make_classifier()
        signals = clf.classify("what is a binary search tree?", _ZERO_EMBED, [], [])
        assert signals.rule_score == 0.0
        assert not any(s.startswith("keyword:") for s in signals.triggered)

    def test_one_keyword_score_half(self) -> None:
        clf = _make_classifier()
        signals = clf.classify("tell me about my investment strategy", _ZERO_EMBED, [], [])
        assert signals.rule_score == pytest.approx(0.5)
        assert any("investment" in s for s in signals.triggered)

    def test_two_keywords_score_one(self) -> None:
        clf = _make_classifier()
        signals = clf.classify("investment and portfolio review", _ZERO_EMBED, [], [])
        assert signals.rule_score == pytest.approx(1.0)

    def test_three_or_more_keywords_capped_at_one(self) -> None:
        clf = _make_classifier()
        # "investment", "portfolio", "career" — three matches
        signals = clf.classify("my investment portfolio and career goals", _ZERO_EMBED, [], [])
        assert signals.rule_score == pytest.approx(1.0)

    def test_word_boundary_prevents_false_positive(self) -> None:
        """'reinvestment' should not match the keyword 'investment'."""
        clf = _make_classifier()
        signals = clf.classify("reinvestment strategy", _ZERO_EMBED, [], [])
        assert signals.rule_score == 0.0

    def test_multi_word_keyword_matched(self) -> None:
        clf = _make_classifier()
        signals = clf.classify("review my meeting notes", _ZERO_EMBED, [], [])
        assert signals.rule_score == pytest.approx(0.5)
        assert any("meeting_notes" in s for s in signals.triggered)

    def test_case_insensitive_match(self) -> None:
        clf = _make_classifier()
        signals = clf.classify("My PORTFOLIO performance", _ZERO_EMBED, [], [])
        assert signals.rule_score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Temporal Signal
# ---------------------------------------------------------------------------

class TestTemporalSignal:
    @pytest.mark.parametrize("phrase", [
        "last year",
        "last month",
        "last week",
        "Q3",
        "2024",
        "yesterday",
        "this week",
        "this month",
        "this year",
    ])
    def test_temporal_phrase_fires_signal(self, phrase: str) -> None:
        clf = _make_classifier([])  # no keywords to isolate signal
        signals = clf.classify(f"what did I do {phrase}?", _ZERO_EMBED, [], [])
        assert signals.temporal_score == pytest.approx(1.0)
        assert any("temporal:" in s for s in signals.triggered)

    def test_no_temporal_phrase_score_zero(self) -> None:
        clf = _make_classifier([])
        signals = clf.classify("what is a hash table?", _ZERO_EMBED, [], [])
        assert signals.temporal_score == 0.0

    def test_only_one_temporal_label_emitted_per_call(self) -> None:
        """Multiple temporal patterns in a single message → only first label added."""
        clf = _make_classifier([])
        signals = clf.classify("last year and last month", _ZERO_EMBED, [], [])
        temporal_labels = [s for s in signals.triggered if s.startswith("temporal:")]
        assert len(temporal_labels) == 1

    def test_year_outside_range_does_not_fire(self) -> None:
        clf = _make_classifier([])
        signals = clf.classify("the event happened in 2010", _ZERO_EMBED, [], [])
        assert signals.temporal_score == 0.0


# ---------------------------------------------------------------------------
# Semantic Signal
# ---------------------------------------------------------------------------

class TestSemanticSignal:
    def test_empty_anchors_yield_zero_semantic_score(self) -> None:
        clf = _make_classifier([])
        signals = clf.classify("investment portfolio", _FINANCE_EMBED, [], [])
        assert signals.semantic_score == 0.0

    def test_similar_query_yields_positive_semantic_score(self) -> None:
        clf = _make_classifier([])
        # anchor is the same vector as query → cosine sim = 1.0
        signals = clf.classify("anything", _FINANCE_EMBED, [_FINANCE_EMBED], ["finance"])
        assert signals.semantic_score > 0.0
        assert any("semantic:" in s for s in signals.triggered)

    def test_orthogonal_query_may_yield_zero_semantic_score(self) -> None:
        clf = _make_classifier([])
        # unrelated embed is orthogonal to finance anchor
        signals = clf.classify("anything", _UNRELATED_EMBED, [_FINANCE_EMBED], ["finance"])
        # cosine sim = 0.0; below INTENT_SEMANTIC_SIMILARITY_MIN → score = 0
        assert signals.semantic_score == 0.0

    def test_semantic_label_includes_best_anchor(self) -> None:
        clf = _make_classifier([])
        signals = clf.classify("anything", _FINANCE_EMBED, [_FINANCE_EMBED], ["finance"])
        semantic_labels = [s for s in signals.triggered if s.startswith("semantic:")]
        assert len(semantic_labels) == 1
        assert "finance" in semantic_labels[0]

    def test_zero_query_embedding_yields_zero_score(self) -> None:
        clf = _make_classifier([])
        signals = clf.classify("anything", _ZERO_EMBED, [_FINANCE_EMBED], ["finance"])
        assert signals.semantic_score == 0.0


# ---------------------------------------------------------------------------
# Composite Score
# ---------------------------------------------------------------------------

class TestCompositeScore:
    def test_all_zeros_yield_zero(self) -> None:
        assert composite_score(_make_signals()) == pytest.approx(0.0)

    def test_all_ones_yield_sum_of_weights(self) -> None:
        score = composite_score(_make_signals(rule=1.0, semantic=1.0, temporal=1.0))
        expected = INTENT_RULE_WEIGHT + INTENT_SEMANTIC_WEIGHT + INTENT_TEMPORAL_WEIGHT
        assert score == pytest.approx(expected)

    def test_keyword_only_below_threshold(self) -> None:
        """Single keyword hit (rule=0.5) should be below INTENT_THRESHOLD alone."""
        score = composite_score(_make_signals(rule=0.5))
        # 0.5 * 0.4 = 0.2 < 0.5 threshold
        assert score < INTENT_THRESHOLD

    def test_keyword_plus_temporal_score_is_correct(self) -> None:
        score = composite_score(_make_signals(rule=0.5, temporal=1.0))
        expected = 0.5 * INTENT_RULE_WEIGHT + 1.0 * INTENT_TEMPORAL_WEIGHT
        assert score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# IntentService (via mocked embedder)
# ---------------------------------------------------------------------------

class TestIntentServiceClassify:
    def _make_service(
        self,
        query_embed: list[float] | None = None,
        anchor_embed: list[float] | None = None,
    ) -> IntentService:
        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = query_embed or _ZERO_EMBED
        mock_embedder.embed_batch.return_value = [anchor_embed or _ZERO_EMBED] * 6
        return IntentService(embedder=mock_embedder, keywords=_KEYWORDS)

    def test_personal_query_requires_context(self) -> None:
        svc = self._make_service()
        # rule_score=1.0 (investment + portfolio), temporal=1.0 (last year)
        # confidence = 1.0*0.4 + 0*0.4 + 1.0*0.2 = 0.6 >= 0.5
        result = svc.classify("my investment portfolio last year")
        assert result.requires_personal_context is True
        assert result.suggested_query is not None

    def test_general_query_does_not_require_context(self) -> None:
        svc = self._make_service()
        result = svc.classify("what is a binary search tree?")
        assert result.requires_personal_context is False
        assert result.suggested_query is None

    def test_suggested_query_strips_politeness_prefix(self) -> None:
        svc = self._make_service()
        result = svc.classify("can you tell me about my investment portfolio last year")
        # rule=1.0, temporal=1.0 → confidence=0.6 — always True here
        assert result.requires_personal_context is True
        assert result.suggested_query is not None
        assert not result.suggested_query.lower().startswith("can you tell me")

    def test_classify_works_gracefully_without_warm_up(self) -> None:
        """classify() falls back to keyword+temporal signals when anchors are empty."""
        svc = self._make_service()
        # warm_up() not called → _anchor_embeddings stays empty → semantic = 0
        result = svc.classify("my investment portfolio last year")
        assert isinstance(result, IntentClassification)
        assert result.requires_personal_context is True  # keyword + temporal sufficient

    def test_warm_up_idempotency(self) -> None:
        """Calling warm_up() twice should embed anchors only once."""
        mock_embedder = MagicMock()
        mock_embedder.embed_batch.return_value = [_FINANCE_EMBED] * 6
        svc = IntentService(embedder=mock_embedder, keywords=_KEYWORDS)

        svc.warm_up()
        svc.warm_up()  # second call must be a no-op

        mock_embedder.embed_batch.assert_called_once()

    def test_semantic_signal_active_after_warm_up(self) -> None:
        """After warm_up, a query aligned with anchors raises the semantic score."""
        mock_embedder = MagicMock()
        # Anchor embeddings are all [1,0,0,0]; query is also [1,0,0,0] → cosine sim = 1.0
        mock_embedder.embed_batch.return_value = [_FINANCE_EMBED] * 6
        mock_embedder.embed_text.return_value = _FINANCE_EMBED
        svc = IntentService(embedder=mock_embedder, keywords=[])  # no keywords → only semantic
        svc.warm_up()

        result = svc.classify("anything")

        # semantic_score = (1.0 - 0.3) / (1.0 - 0.3) = 1.0; confidence = 1.0 * 0.4 = 0.4
        # < INTENT_THRESHOLD (0.5), but signal is active (score > 0)
        assert any("semantic:" in s for s in result.triggered_signals)
        assert result.confidence > 0.0

    def test_confidence_is_rounded_to_4_decimals(self) -> None:
        svc = self._make_service()
        result = svc.classify("my investment portfolio last year")
        assert result.confidence == round(result.confidence, 4)

    def test_empty_message_returns_no_context(self) -> None:
        """A single-space or stripped empty message should not trigger any signal."""
        svc = self._make_service()
        # FastAPI validates min_length=1, but service-level test with whitespace
        result = svc.classify(" ")
        assert result.requires_personal_context is False


# ---------------------------------------------------------------------------
# API endpoint integration tests
# ---------------------------------------------------------------------------

class TestIntentClassifyEndpoint:
    def test_returns_200_with_valid_message(
        self, client: TestClient, mock_intent_service: MagicMock
    ) -> None:
        mock_intent_service.classify.return_value = IntentClassification(
            requires_personal_context=True,
            confidence=0.82,
            triggered_signals=["keyword:investment", "temporal:last_year"],
            suggested_query="investment return last year",
        )
        resp = client.post("/intent/classify", json={"message": "my investment last year"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["requires_personal_context"] is True
        assert body["confidence"] == pytest.approx(0.82)
        assert "keyword:investment" in body["triggered_signals"]
        assert body["suggested_query"] == "investment return last year"

    def test_returns_200_for_general_query(
        self, client: TestClient, mock_intent_service: MagicMock
    ) -> None:
        mock_intent_service.classify.return_value = IntentClassification(
            requires_personal_context=False,
            confidence=0.05,
            triggered_signals=[],
            suggested_query=None,
        )
        resp = client.post("/intent/classify", json={"message": "what is recursion?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["requires_personal_context"] is False
        assert body["suggested_query"] is None

    def test_returns_422_for_empty_message(self, client: TestClient) -> None:
        resp = client.post("/intent/classify", json={"message": ""})
        assert resp.status_code == 422

    def test_returns_422_for_missing_message(self, client: TestClient) -> None:
        resp = client.post("/intent/classify", json={})
        assert resp.status_code == 422

    def test_returns_503_on_service_exception(
        self, client: TestClient, mock_intent_service: MagicMock
    ) -> None:
        mock_intent_service.classify.side_effect = RuntimeError("embedding model unavailable")
        resp = client.post("/intent/classify", json={"message": "my investment notes"})
        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "INTENT_CLASSIFIER_UNAVAILABLE"

    def test_delegates_message_to_service(
        self, client: TestClient, mock_intent_service: MagicMock
    ) -> None:
        mock_intent_service.classify.return_value = IntentClassification(
            requires_personal_context=False,
            confidence=0.0,
            triggered_signals=[],
            suggested_query=None,
        )
        client.post("/intent/classify", json={"message": "hello world"})
        mock_intent_service.classify.assert_called_once_with("hello world")
