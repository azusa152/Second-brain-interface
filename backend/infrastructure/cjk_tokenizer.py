"""CJK-aware tokenizer for BM25 sparse indexing.

Pre-processes text containing Chinese/Japanese characters before passing to
fastembed's BM25 model, which assumes whitespace-delimited tokens.

- Japanese: morphological analysis via SudachiPy with POS-based stopword removal
- Chinese: word segmentation via jieba with POS-based stopword removal
- Non-CJK: passed through unchanged

POS filtering is applied ONLY for sparse/BM25 indexing. Dense embeddings
receive NFKC-normalized text (plus invisible-character sanitization) with no
POS filtering so the neural model retains grammatical context.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from backend.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Unicode ranges for CJK detection
# ---------------------------------------------------------------------------

_CJK_UNIFIED = re.compile(
    r"[\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Extension A
    r"\U00020000-\U0002a6df"  # CJK Extension B
    r"\uf900-\ufaff"  # CJK Compatibility Ideographs
    r"]"
)

_JAPANESE_KANA = re.compile(
    r"[\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"]"
)

_INVISIBLE_RE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f"  # zero-width space/joiner/marks
    r"\ufeff"  # BOM
    r"\u00ad"  # soft hyphen
    r"\u2060\u2061\u2062\u2063"  # word joiner, invisible operators
    r"\u180e"  # Mongolian vowel separator
    r"]"
)

# ---------------------------------------------------------------------------
# Japanese POS categories to KEEP (content words only).
# Sudachi part_of_speech() returns a list like ['名詞', '普通名詞', '一般', ...].
# We check the first element against this allow-set.
# ---------------------------------------------------------------------------

_JA_CONTENT_POS = frozenset({
    "名詞",  # nouns
    "動詞",  # verbs
    "形容詞",  # i-adjectives
    "形状詞",  # na-adjectives (adjectival nouns)
    "副詞",  # adverbs
    "連体詞",  # pre-noun adjectival
    "感動詞",  # interjections (rare, but carry meaning)
})

# ---------------------------------------------------------------------------
# Chinese POS tags to REMOVE (function words).
# jieba.posseg uses ICTCLAS-compatible single-letter tags.
# ---------------------------------------------------------------------------

# jieba POS tags are multi-character (e.g. "uj" for 的, "ud" for 得).
# We match by prefix so "u" catches all 助词 subtypes (uj, ud, uz, ul, etc.).
_ZH_STOP_POS_PREFIXES = (
    "u",  # 助词 (particles): 的(uj), 了(ul), 着(uz), 过(ug), 地(ud), 得(ud)
    "p",  # 介词 (prepositions): 在, 从, 对, 关于, 按照
    "c",  # 连词 (conjunctions): 和, 与, 而, 但, 或
    "e",  # 叹词 (interjections used as filler)
    "y",  # 语气词 (modal particles): 吗, 呢, 吧, 啊
    "w",  # 标点 (punctuation)
    "x",  # 非语素字 (non-morpheme characters)
    "o",  # 拟声词 (onomatopoeia, generally noise for search)
)


def _has_cjk(text: str) -> bool:
    """Return True if text contains any CJK unified ideograph."""
    return bool(_CJK_UNIFIED.search(text))


def has_cjk(text: str) -> bool:
    """Public wrapper for shared CJK detection across modules."""
    return _has_cjk(text)


def _has_japanese_kana(text: str) -> bool:
    """Return True if text contains hiragana or katakana."""
    return bool(_JAPANESE_KANA.search(text))


def has_japanese_kana(text: str) -> bool:
    """Public wrapper for shared kana detection across modules."""
    return _has_japanese_kana(text)


def _is_japanese(text: str) -> bool:
    """Heuristic: text is Japanese if it contains kana, or CJK + kana mix."""
    return _has_japanese_kana(text)


def _is_chinese(text: str) -> bool:
    """Heuristic: text contains CJK ideographs but no Japanese kana."""
    return _has_cjk(text) and not _has_japanese_kana(text)


def _strip_invisible(text: str) -> str:
    """Remove invisible Unicode characters that can corrupt tokenization."""
    return _INVISIBLE_RE.sub("", text)


def _normalize_and_sanitize(text: str) -> tuple[str, str]:
    """Return (NFKC normalized text, sanitized text)."""
    normalized = unicodedata.normalize("NFKC", text)
    sanitized = _strip_invisible(normalized)
    return normalized, sanitized


def nfkc_normalize(text: str) -> str:
    """Normalize full-width characters and strip invisible Unicode artifacts."""
    _, sanitized = _normalize_and_sanitize(text)
    return sanitized


# ---------------------------------------------------------------------------
# Lazy-loaded tokenizers (heavy dictionary loading happens once on first call)
# ---------------------------------------------------------------------------

_sudachi_tokenizer = None
_sudachi_split_mode = None
_sudachi_available: bool | None = None

_jieba_available: bool | None = None


def _ensure_sudachi() -> bool:
    """Lazy-load SudachiPy; return True if available."""
    global _sudachi_tokenizer, _sudachi_split_mode, _sudachi_available  # noqa: PLW0603
    if _sudachi_available is not None:
        return _sudachi_available
    try:
        from sudachipy import Dictionary, SplitMode

        _sudachi_tokenizer = Dictionary().create()
        _sudachi_split_mode = SplitMode.A  # most granular segmentation
        _sudachi_available = True
        logger.info("SudachiPy loaded successfully")
    except ImportError:
        _sudachi_available = False
        logger.warning(
            "SudachiPy not installed — Japanese tokenization disabled. "
            "Install with: pip install sudachipy sudachidict_core"
        )
    return _sudachi_available


def _ensure_jieba() -> bool:
    """Lazy-load jieba; return True if available."""
    global _jieba_available  # noqa: PLW0603
    if _jieba_available is not None:
        return _jieba_available
    try:
        import jieba

        jieba.setLogLevel(20)  # suppress jieba's noisy INFO logs
        _jieba_available = True
        logger.info("jieba loaded successfully")
    except ImportError:
        _jieba_available = False
        logger.warning(
            "jieba not installed — Chinese tokenization disabled. "
            "Install with: pip install jieba"
        )
    return _jieba_available


# ---------------------------------------------------------------------------
# Tokenization functions
# ---------------------------------------------------------------------------


def _tokenize_japanese(text: str) -> str:
    """Segment Japanese text with Sudachi, keeping only content-word POS."""
    tokenized, _ = _tokenize_japanese_with_details(text, collect_debug=False)
    return tokenized


def _tokenize_chinese(text: str) -> str:
    """Segment Chinese text with jieba, removing function-word POS tags."""
    tokenized, _ = _tokenize_chinese_with_details(text, collect_debug=False)
    return tokenized


def _is_zh_function_pos(flag: str) -> bool:
    """Return True when jieba POS tag is a Chinese function-word category."""
    if flag == "eng":
        return False
    return flag.startswith(_ZH_STOP_POS_PREFIXES)


def tokenize_for_sparse(text: str) -> str:
    """Pre-process text for BM25 sparse embedding.

    Applies NFKC normalization and CJK-aware word segmentation with
    POS-based stopword removal.  Non-CJK text is passed through after
    normalization only (fastembed's BM25 tokenizer handles English well).
    """
    _, text = _normalize_and_sanitize(text)
    sparse_output, _, _, _ = _run_sparse_pipeline(text, collect_debug=False)
    return sparse_output


def _tokenize_japanese_with_details(
    text: str, *, collect_debug: bool
) -> tuple[str, list[dict[str, Any]]]:
    """Segment Japanese text and optionally emit token-level details."""
    if not _ensure_sudachi():
        if not collect_debug:
            return text, []
        return text, [{"surface": text, "pos": "missing_sudachi", "kept": True, "language": "japanese"}]

    assert _sudachi_tokenizer is not None
    assert _sudachi_split_mode is not None

    morphemes = _sudachi_tokenizer.tokenize(text, _sudachi_split_mode)
    kept_tokens: list[str] = []
    debug_tokens: list[dict[str, Any]] = []
    for m in morphemes:
        pos = m.part_of_speech()
        primary_pos = pos[0]
        kept = primary_pos in _JA_CONTENT_POS
        surface = m.surface()
        normalized = m.normalized_form()
        if kept and normalized.strip():
            kept_tokens.append(normalized)
        if collect_debug:
            debug_tokens.append(
                {
                    "surface": surface,
                    "normalized": normalized,
                    "pos": primary_pos,
                    "kept": kept,
                    "language": "japanese",
                }
            )
    return " ".join(kept_tokens), debug_tokens


def _tokenize_chinese_with_details(
    text: str, *, collect_debug: bool
) -> tuple[str, list[dict[str, Any]]]:
    """Segment Chinese text and optionally emit token-level details."""
    if not _ensure_jieba():
        if not collect_debug:
            return text, []
        return text, [{"surface": text, "pos": "missing_jieba", "kept": True, "language": "chinese"}]

    import jieba.posseg as pseg

    kept_tokens: list[str] = []
    debug_tokens: list[dict[str, Any]] = []
    for word, flag in pseg.cut(text):
        kept = (not _is_zh_function_pos(flag)) and bool(word.strip())
        if kept:
            kept_tokens.append(word)
        if collect_debug:
            debug_tokens.append(
                {
                    "surface": word,
                    "pos": flag,
                    "kept": kept,
                    "language": "chinese",
                }
            )
    return " ".join(kept_tokens), debug_tokens


def _run_sparse_pipeline(
    sanitized_text: str, *, collect_debug: bool
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Run shared sparse pipeline and optionally collect debug details."""
    detected_language = "other"
    if not (_has_cjk(sanitized_text) or _has_japanese_kana(sanitized_text)):
        return sanitized_text, detected_language, [], []

    segments = _split_cjk_segments(sanitized_text)
    processed: list[str] = []
    segment_debug: list[dict[str, Any]] = []
    token_debug: list[dict[str, Any]] = []

    for segment, is_cjk_segment in segments:
        if not is_cjk_segment:
            if collect_debug:
                segment_debug.append({"text": segment, "is_cjk": False, "language": "other"})
            processed.append(segment)
            continue

        if _is_japanese(segment):
            detected_language = "japanese"
            tokenized, tokens = _tokenize_japanese_with_details(segment, collect_debug=collect_debug)
            if collect_debug:
                segment_debug.append({"text": segment, "is_cjk": True, "language": "japanese"})
                token_debug.extend(tokens)
            processed.append(tokenized)
            continue

        detected_language = "chinese"
        tokenized, tokens = _tokenize_chinese_with_details(segment, collect_debug=collect_debug)
        if collect_debug:
            segment_debug.append({"text": segment, "is_cjk": True, "language": "chinese"})
            token_debug.extend(tokens)
        processed.append(tokenized)

    sparse_output = " ".join(part for part in processed if part.strip())
    return sparse_output, detected_language, segment_debug, token_debug


def tokenize_for_sparse_debug(text: str) -> dict[str, Any]:
    """Debug helper that returns tokenization output with intermediate details."""
    normalized, sanitized = _normalize_and_sanitize(text)
    sparse_output, detected_language, segments, tokens = _run_sparse_pipeline(
        sanitized,
        collect_debug=True,
    )
    return {
        "original": text,
        "normalized": normalized,
        "sanitized": sanitized,
        "segments": segments,
        "tokens": tokens,
        "detected_language": detected_language,
        "sparse_output": sparse_output,
    }


# ---------------------------------------------------------------------------
# Segment splitter for mixed-language text
# ---------------------------------------------------------------------------

_CJK_CHAR_RE = re.compile(
    r"([\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff\u3400-\u4dbf"
    r"\uf900-\ufaff\U00020000-\U0002a6df]+)"
)


def _split_cjk_segments(text: str) -> list[tuple[str, bool]]:
    """Split text into alternating (segment, is_cjk) tuples.

    CJK runs (kana + ideographs) are separated from non-CJK runs so each
    can be tokenized by the appropriate engine.
    """
    parts: list[tuple[str, bool]] = []
    last_end = 0
    for match in _CJK_CHAR_RE.finditer(text):
        if match.start() > last_end:
            parts.append((text[last_end : match.start()], False))
        parts.append((match.group(0), True))
        last_end = match.end()
    if last_end < len(text):
        parts.append((text[last_end:], False))
    return parts


# ---------------------------------------------------------------------------
# CJK-aware word counter (for MarkdownParser)
# ---------------------------------------------------------------------------


def count_words_cjk_aware(text: str) -> int:
    """Count words in text, treating each CJK character as one word.

    For non-CJK segments, standard whitespace splitting is used.
    """
    total = 0
    for segment, is_cjk in _split_cjk_segments(text):
        if is_cjk:
            total += len(segment)
        else:
            total += len(segment.split())
    return total
