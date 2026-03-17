"""Unit tests for CJK tokenizer (BM25 pre-processing)."""

import pytest

from backend.infrastructure.cjk_tokenizer import (
    _has_cjk,
    _has_japanese_kana,
    _is_chinese,
    _is_japanese,
    _split_cjk_segments,
    count_words_cjk_aware,
    nfkc_normalize,
    tokenize_for_sparse,
)

# ---------------------------------------------------------------------------
# NFKC normalization
# ---------------------------------------------------------------------------


class TestNfkcNormalize:
    def test_should_convert_fullwidth_ascii_to_halfwidth(self) -> None:
        assert nfkc_normalize("Ａ") == "A"
        assert nfkc_normalize("１２３") == "123"

    def test_should_preserve_normal_ascii(self) -> None:
        assert nfkc_normalize("hello world") == "hello world"

    def test_should_preserve_cjk_characters(self) -> None:
        assert nfkc_normalize("漢字") == "漢字"

    def test_should_normalize_fullwidth_katakana(self) -> None:
        result = nfkc_normalize("ﾃﾞｰﾀﾍﾞｰｽ")
        assert "データベース" == result


# ---------------------------------------------------------------------------
# CJK detection helpers
# ---------------------------------------------------------------------------


class TestCjkDetection:
    def test_has_cjk_should_detect_chinese_characters(self) -> None:
        assert _has_cjk("数据库设计")

    def test_has_cjk_should_detect_kanji(self) -> None:
        assert _has_cjk("設計")

    def test_has_cjk_should_reject_pure_ascii(self) -> None:
        assert not _has_cjk("hello world")

    def test_has_cjk_should_reject_pure_kana(self) -> None:
        assert not _has_cjk("ひらがな")

    def test_has_japanese_kana_should_detect_hiragana(self) -> None:
        assert _has_japanese_kana("について")

    def test_has_japanese_kana_should_detect_katakana(self) -> None:
        assert _has_japanese_kana("データベース")

    def test_has_japanese_kana_should_reject_pure_chinese(self) -> None:
        assert not _has_japanese_kana("数据库")

    def test_is_japanese_should_detect_mixed_kanji_kana(self) -> None:
        assert _is_japanese("データベース設計について")

    def test_is_chinese_should_detect_pure_hanzi(self) -> None:
        assert _is_chinese("数据库设计")

    def test_is_chinese_should_reject_text_with_kana(self) -> None:
        assert not _is_chinese("データベース設計")


# ---------------------------------------------------------------------------
# Segment splitter
# ---------------------------------------------------------------------------


class TestSplitCjkSegments:
    def test_should_split_mixed_language_text(self) -> None:
        segments = _split_cjk_segments("Hello 設計 World")
        assert len(segments) == 3
        assert segments[0] == ("Hello ", False)
        assert segments[1] == ("設計", True)
        assert segments[2] == (" World", False)

    def test_should_handle_pure_ascii(self) -> None:
        segments = _split_cjk_segments("hello world")
        assert len(segments) == 1
        assert segments[0] == ("hello world", False)

    def test_should_handle_pure_cjk(self) -> None:
        segments = _split_cjk_segments("データベース設計")
        assert len(segments) == 1
        assert segments[0][1] is True

    def test_should_handle_empty_string(self) -> None:
        segments = _split_cjk_segments("")
        assert segments == []


# ---------------------------------------------------------------------------
# CJK-aware word count
# ---------------------------------------------------------------------------


class TestCountWordsCjkAware:
    def test_should_count_english_words_normally(self) -> None:
        assert count_words_cjk_aware("hello world foo") == 3

    def test_should_count_each_cjk_character_as_one_word(self) -> None:
        assert count_words_cjk_aware("数据库") == 3

    def test_should_handle_mixed_language(self) -> None:
        # "hello" (1 word) + "設計" (2 chars) = 3
        assert count_words_cjk_aware("hello 設計") == 3

    def test_should_count_japanese_kana_as_cjk(self) -> None:
        # Each kana char counts as one word
        assert count_words_cjk_aware("データ") == 3

    def test_should_handle_empty_string(self) -> None:
        assert count_words_cjk_aware("") == 0


# ---------------------------------------------------------------------------
# tokenize_for_sparse — English passthrough
# ---------------------------------------------------------------------------


class TestTokenizeForSparseEnglish:
    def test_should_pass_through_english_text(self) -> None:
        text = "database design patterns"
        assert tokenize_for_sparse(text) == text

    def test_should_normalize_fullwidth_in_english(self) -> None:
        assert tokenize_for_sparse("ＡＢＣ") == "ABC"


# ---------------------------------------------------------------------------
# tokenize_for_sparse — Japanese (requires sudachi)
# ---------------------------------------------------------------------------


class TestTokenizeForSparseJapanese:
    @pytest.fixture(autouse=True)
    def _reset_sudachi_state(self) -> None:
        """Reset lazy-load state between tests."""
        import backend.infrastructure.cjk_tokenizer as mod

        mod._sudachi_available = None
        mod._sudachi_tokenizer = None
        mod._sudachi_split_mode = None

    def test_should_segment_and_filter_particles(self) -> None:
        """Sudachi should remove 助詞 like 'について'."""
        result = tokenize_for_sparse("データベース設計について")
        assert "について" not in result
        # Content words should be present (exact form depends on Sudachi dict)
        assert "データベース" in result or "データ" in result
        assert "設計" in result

    def test_should_remove_auxiliary_verbs(self) -> None:
        result = tokenize_for_sparse("設計されました")
        # 助動詞 like ました should be filtered
        assert "ました" not in result
        assert "設計" in result

    def test_should_handle_mixed_jp_english(self) -> None:
        result = tokenize_for_sparse("API設計について")
        assert "について" not in result
        assert "API" in result or "設計" in result

    def test_should_gracefully_handle_missing_sudachi(self) -> None:
        """When SudachiPy is not installed, text should pass through."""
        import backend.infrastructure.cjk_tokenizer as mod

        mod._sudachi_available = False
        result = tokenize_for_sparse("データベース設計について")
        assert "について" in result
        mod._sudachi_available = None


# ---------------------------------------------------------------------------
# tokenize_for_sparse — Chinese (requires jieba)
# ---------------------------------------------------------------------------


class TestTokenizeForSparseChinese:
    @pytest.fixture(autouse=True)
    def _reset_jieba_state(self) -> None:
        """Reset lazy-load state between tests."""
        import backend.infrastructure.cjk_tokenizer as mod

        mod._jieba_available = None

    def test_should_segment_and_filter_stopwords(self) -> None:
        """jieba should remove function words like 的, 关于."""
        result = tokenize_for_sparse("关于数据库设计的最佳实践")
        assert "的" not in result.split()
        # Content words should survive
        assert "数据库" in result or "数据" in result
        assert "设计" in result

    def test_should_keep_content_words(self) -> None:
        result = tokenize_for_sparse("机器学习算法")
        assert "机器" in result or "学习" in result or "算法" in result

    def test_should_keep_embedded_english_words(self) -> None:
        result = tokenize_for_sparse("使用Docker部署AI服务")
        tokens = result.split()
        assert "Docker" in tokens
        assert "AI" in tokens

    def test_should_gracefully_handle_missing_jieba(self) -> None:
        """When jieba is not installed, text should pass through."""
        import backend.infrastructure.cjk_tokenizer as mod

        mod._jieba_available = False
        result = tokenize_for_sparse("关于数据库设计的最佳实践")
        assert "关于" in result
        mod._jieba_available = None
