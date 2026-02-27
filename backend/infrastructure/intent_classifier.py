"""Multi-signal intent classifier for personal knowledge retrieval routing.

Combines three orthogonal signals:
  1. Keyword signal  — fast word-boundary regex matching against domain keywords
  2. Semantic signal — cosine similarity against pre-computed domain anchor embeddings
  3. Temporal signal — regex detection of time references indicating personal context

All state (keywords, patterns) is injected at construction time.
The classifier is stateless after construction: classify() is a pure function.
"""

import re
from dataclasses import dataclass, field

import numpy as np

from backend.domain.constants import (
    INTENT_RULE_WEIGHT,
    INTENT_SEMANTIC_SIMILARITY_MIN,
    INTENT_SEMANTIC_WEIGHT,
    INTENT_TEMPORAL_WEIGHT,
)

# Compiled temporal patterns. Covers the most common personal-context time references.
_TEMPORAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\blast\s+year\b", re.IGNORECASE),
    re.compile(r"\blast\s+month\b", re.IGNORECASE),
    re.compile(r"\blast\s+week\b", re.IGNORECASE),
    re.compile(r"\bQ[1-4]\b"),
    re.compile(r"\b20[2-3]\d\b"),  # 2020-2039
    re.compile(r"\byesterday\b", re.IGNORECASE),
    re.compile(r"\bthis\s+week\b", re.IGNORECASE),
    re.compile(r"\bthis\s+month\b", re.IGNORECASE),
    re.compile(r"\bthis\s+year\b", re.IGNORECASE),
]

# Politeness prefixes to strip when building the suggested query.
# Only prefixes are stripped — stopwords/pronouns inside the query are preserved
# because the existing hybrid search handles natural language well.
_POLITENESS_PREFIX = re.compile(
    r"^(?:"
    r"can you tell me|could you tell me|"
    r"please(?:\s+tell me|\s+find|\s+show me|\s+help me find)?|"
    r"i(?:'d| would) like to know|i want to know|"
    r"tell me(?:\s+about)?|do you know(?:\s+about)?|"
    r"what can you tell me about"
    r")\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClassifierSignals:
    """Immutable raw signal scores from a single classify() call."""

    rule_score: float  # 0.0-1.0 from keyword matching
    semantic_score: float  # 0.0-1.0 from embedding cosine similarity
    temporal_score: float  # 0.0 or 1.0 from temporal heuristic
    triggered: tuple[str, ...] = field(default_factory=tuple)  # Human-readable labels


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [-1, 1]; returns 0.0 for zero-norm vectors."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def composite_score(signals: ClassifierSignals) -> float:
    """Compute the weighted composite confidence score from raw signal scores."""
    return (
        signals.rule_score * INTENT_RULE_WEIGHT
        + signals.semantic_score * INTENT_SEMANTIC_WEIGHT
        + signals.temporal_score * INTENT_TEMPORAL_WEIGHT
    )


def strip_politeness_prefix(message: str) -> str:
    """Remove common conversational prefixes that add no search value.

    Returns the stripped string, or the original message if no prefix matched.
    """
    return _POLITENESS_PREFIX.sub("", message).strip()


class IntentClassifier:
    """Stateless multi-signal classifier.

    All expensive state (compiled keyword patterns, temporal patterns) is
    built once at construction time. classify() accepts pre-computed anchor
    embeddings so no I/O or model inference happens inside classify().
    """

    def __init__(
        self,
        keywords: list[str],
        temporal_patterns: list[re.Pattern[str]] | None = None,
    ) -> None:
        # Compile keyword → word-boundary pattern pairs once
        self._keyword_patterns: list[tuple[str, re.Pattern[str]]] = [
            (kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)) for kw in keywords
        ]
        self._temporal_patterns = temporal_patterns or _TEMPORAL_PATTERNS

    def classify(
        self,
        message: str,
        query_embedding: list[float],
        anchor_embeddings: list[list[float]],
        anchor_labels: list[str],
    ) -> ClassifierSignals:
        """Compute the three signals and return raw scores with labels.

        Args:
            message: Raw user message (lowercasing is done internally).
            query_embedding: Pre-computed dense embedding of the message.
            anchor_embeddings: Pre-warmed embeddings for each domain anchor.
            anchor_labels: Human-readable label for each anchor (same order).

        Returns:
            ClassifierSignals with scores in [0, 1] and triggered signal labels.
        """
        triggered: list[str] = []

        # --- Signal 1: Keyword ---
        matched_keywords: list[str] = [
            kw for kw, pat in self._keyword_patterns if pat.search(message)
        ]
        rule_score = min(1.0, len(matched_keywords) / 2)
        for kw in matched_keywords:
            triggered.append(f"keyword:{kw.replace(' ', '_')}")

        # --- Signal 2: Semantic ---
        semantic_score = 0.0
        if anchor_embeddings and query_embedding:
            sims = [cosine_similarity(query_embedding, anchor) for anchor in anchor_embeddings]
            max_sim = max(sims)
            best_idx = sims.index(max_sim)
            # Normalise to [0, 1]: scores below MIN contribute nothing
            denom = 1.0 - INTENT_SEMANTIC_SIMILARITY_MIN
            semantic_score = max(0.0, (max_sim - INTENT_SEMANTIC_SIMILARITY_MIN) / denom)
            if semantic_score > 0:
                label = anchor_labels[best_idx] if best_idx < len(anchor_labels) else str(best_idx)
                triggered.append(f"semantic:{max_sim:.2f}:{label}")

        # --- Signal 3: Temporal ---
        temporal_score = 0.0
        for pat in self._temporal_patterns:
            match = pat.search(message)
            if match:
                triggered.append(f"temporal:{match.group(0).lower().replace(' ', '_')}")
                temporal_score = 1.0
                break  # one temporal hit is sufficient

        return ClassifierSignals(
            rule_score=rule_score,
            semantic_score=semantic_score,
            temporal_score=temporal_score,
            triggered=tuple(triggered),
        )
