import re
from collections import Counter

from rapidfuzz import fuzz, process

from backend.domain.constants import FUZZY_MAX_CANDIDATES, FUZZY_MIN_SCORE, FUZZY_MIN_TERM_LENGTH

_TERM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_TOKEN_PATTERN = re.compile(r"\w+|\W+")
_CJK_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class FuzzyMatcher:
    """In-memory vocabulary matcher for typo-tolerant query correction."""

    def __init__(
        self,
        min_score: int = FUZZY_MIN_SCORE,
        min_term_length: int = FUZZY_MIN_TERM_LENGTH,
        max_candidates: int = FUZZY_MAX_CANDIDATES,
    ) -> None:
        self._min_score = min_score
        self._min_term_length = min_term_length
        self._max_candidates = max_candidates
        self._vocabulary: list[str] = []
        self._display_by_term: dict[str, str] = {}

    def rebuild_vocabulary(self, titles: list[str], headings: list[str]) -> None:
        """Build searchable term vocabulary from note titles and heading contexts."""
        term_counter: Counter[str] = Counter()
        display_counter: dict[str, Counter[str]] = {}

        for source in titles + headings:
            for token in _TERM_PATTERN.findall(source):
                normalized = token.casefold()
                if len(normalized) < self._min_term_length:
                    continue
                if _CJK_PATTERN.search(normalized):
                    continue
                if normalized.isdigit():
                    continue
                term_counter[normalized] += 1
                display_counter.setdefault(normalized, Counter())[token] += 1

        self._vocabulary = [term for term, _ in term_counter.most_common()]
        self._display_by_term = {
            term: display_counts.most_common(1)[0][0]
            for term, display_counts in display_counter.items()
        }

    def correct_query(self, query: str) -> tuple[str, str | None]:
        """Return sparse-query correction and optional user-facing suggestion."""
        if not self._vocabulary:
            return query, None

        corrected_parts: list[str] = []
        changed = False

        for token in _TOKEN_PATTERN.findall(query):
            normalized = token.casefold()
            if not self._should_correct_token(token, normalized):
                corrected_parts.append(token)
                continue

            candidates = process.extract(
                normalized,
                self._vocabulary,
                scorer=fuzz.ratio,
                score_cutoff=self._min_score,
                limit=self._max_candidates,
            )
            if not candidates:
                corrected_parts.append(token)
                continue

            corrected_term = self._display_by_term.get(candidates[0][0], token)
            if corrected_term.casefold() != normalized:
                changed = True
                corrected_parts.append(corrected_term)
            else:
                corrected_parts.append(token)

        corrected_query = "".join(corrected_parts)
        did_you_mean = corrected_query if changed and corrected_query != query else None
        return corrected_query, did_you_mean

    def _should_correct_token(self, token: str, normalized: str) -> bool:
        """Return True if token is suitable for typo correction."""
        if len(normalized) < self._min_term_length:
            return False
        if _CJK_PATTERN.search(token):
            return False
        if normalized.isdigit():
            return False
        if not _TERM_PATTERN.fullmatch(token):
            return False
        return True
