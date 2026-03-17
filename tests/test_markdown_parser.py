import os

from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.vault_file_map import VaultFileMap

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "test_vault")


def _make_parser() -> MarkdownParser:
    file_map = VaultFileMap(FIXTURES_DIR)
    file_map.scan()
    return MarkdownParser(file_map)


class TestFrontmatterExtraction:
    def test_parse_should_extract_title_from_frontmatter(self) -> None:
        parser = _make_parser()
        content = "---\ntitle: My Title\n---\n\nBody text."

        metadata, _ = parser.parse("test.md", content)
        assert metadata.title == "My Title"

    def test_parse_should_extract_tags_from_frontmatter(self) -> None:
        parser = _make_parser()
        content = "---\ntags:\n  - python\n  - testing\n---\n\nBody."

        metadata, _ = parser.parse("test.md", content)
        assert "python" in metadata.tags
        assert "testing" in metadata.tags

    def test_parse_should_fall_back_to_h1_for_title(self) -> None:
        parser = _make_parser()
        content = "# Heading Title\n\nBody text."

        metadata, _ = parser.parse("test.md", content)
        assert metadata.title == "Heading Title"

    def test_parse_should_fall_back_to_filename_for_title(self) -> None:
        parser = _make_parser()
        content = "Just body text, no frontmatter or heading."

        metadata, _ = parser.parse("my-note.md", content)
        assert metadata.title == "my-note"

    def test_parse_should_handle_empty_frontmatter(self) -> None:
        parser = _make_parser()
        content = "---\n---\n\nBody."

        metadata, _ = parser.parse("test.md", content)
        assert metadata.frontmatter == {}

    def test_parse_should_handle_invalid_yaml(self) -> None:
        parser = _make_parser()
        content = "---\n: invalid yaml [\n---\n\nBody."

        metadata, _ = parser.parse("test.md", content)
        assert metadata.frontmatter == {}


class TestTagExtraction:
    def test_parse_should_extract_inline_tags(self) -> None:
        parser = _make_parser()
        content = "Some text with #python and #testing tags."

        metadata, _ = parser.parse("test.md", content)
        assert "python" in metadata.tags
        assert "testing" in metadata.tags

    def test_parse_should_merge_frontmatter_and_inline_tags(self) -> None:
        parser = _make_parser()
        content = "---\ntags:\n  - yaml-tag\n---\n\nText with #inline-tag."

        metadata, _ = parser.parse("test.md", content)
        assert "yaml-tag" in metadata.tags
        assert "inline-tag" in metadata.tags

    def test_parse_should_skip_tags_in_code_blocks(self) -> None:
        parser = _make_parser()
        content = "Normal #real-tag and\n```\n#not-a-tag\n```"

        metadata, _ = parser.parse("test.md", content)
        assert "real-tag" in metadata.tags
        assert "not-a-tag" not in metadata.tags


class TestWikilinkExtraction:
    def test_parse_should_extract_wikilinks(self) -> None:
        parser = _make_parser()
        content = "See [[architecture]] for details."

        _, links = parser.parse("test.md", content)
        assert len(links) == 1
        assert links[0].link_text == "architecture"
        assert links[0].source_path == "test.md"

    def test_parse_should_resolve_wikilinks_via_vault_map(self) -> None:
        parser = _make_parser()
        content = "See [[architecture]] for details."

        _, links = parser.parse("test.md", content)
        assert links[0].resolved_target_path == os.path.join("concepts", "architecture.md")

    def test_parse_should_handle_aliased_links(self) -> None:
        parser = _make_parser()
        content = "See [[architecture|system design]] for details."

        _, links = parser.parse("test.md", content)
        assert links[0].link_text == "architecture"

    def test_parse_should_deduplicate_wikilinks(self) -> None:
        parser = _make_parser()
        content = "First [[architecture]] and second [[architecture]]."

        _, links = parser.parse("test.md", content)
        assert len(links) == 1

    def test_parse_should_skip_links_in_code_blocks(self) -> None:
        parser = _make_parser()
        content = "Real [[architecture]] and\n```\n[[not-a-link]]\n```"

        _, links = parser.parse("test.md", content)
        assert len(links) == 1
        assert links[0].link_text == "architecture"

    def test_parse_should_handle_unresolvable_links(self) -> None:
        parser = _make_parser()
        content = "See [[nonexistent-note]] here."

        _, links = parser.parse("test.md", content)
        assert len(links) == 1
        assert links[0].resolved_target_path is None


class TestCjkTagExtraction:
    def test_parse_should_extract_japanese_tags(self) -> None:
        parser = _make_parser()
        content = "Text with #日記 tag."

        metadata, _ = parser.parse("test.md", content)
        assert "日記" in metadata.tags

    def test_parse_should_extract_katakana_tags(self) -> None:
        parser = _make_parser()
        content = "Text with #データベース tag."

        metadata, _ = parser.parse("test.md", content)
        assert "データベース" in metadata.tags

    def test_parse_should_extract_chinese_tags(self) -> None:
        parser = _make_parser()
        content = "Text with #数据库 tag."

        metadata, _ = parser.parse("test.md", content)
        assert "数据库" in metadata.tags

    def test_parse_should_extract_cjk_extension_a_tags(self) -> None:
        parser = _make_parser()
        content = "Text with #㐀研究 tag."

        metadata, _ = parser.parse("test.md", content)
        assert "㐀研究" in metadata.tags

    def test_parse_should_extract_mixed_cjk_ascii_tags(self) -> None:
        parser = _make_parser()
        content = "Text with #DB設計 tag."

        metadata, _ = parser.parse("test.md", content)
        assert "DB設計" in metadata.tags

    def test_parse_should_still_extract_ascii_tags(self) -> None:
        parser = _make_parser()
        content = "Text with #python and #日記 tags."

        metadata, _ = parser.parse("test.md", content)
        assert "python" in metadata.tags
        assert "日記" in metadata.tags


class TestWordCount:
    def test_parse_should_count_words_in_body(self) -> None:
        parser = _make_parser()
        content = "---\ntitle: Test\n---\n\nOne two three four five."

        metadata, _ = parser.parse("test.md", content)
        assert metadata.word_count == 5

    def test_parse_should_count_cjk_characters_as_words(self) -> None:
        parser = _make_parser()
        content = "---\ntitle: Test\n---\n\n数据库设计"

        metadata, _ = parser.parse("test.md", content)
        assert metadata.word_count == 5  # 数 + 据 + 库 + 设 + 计 = 5 CJK chars

    def test_parse_should_count_mixed_language_words(self) -> None:
        parser = _make_parser()
        content = "---\ntitle: Test\n---\n\nhello 設計 world"

        metadata, _ = parser.parse("test.md", content)
        # "hello" (1) + "設計" (2 CJK chars) + "world" (1) = 4
        assert metadata.word_count == 4


class TestGetBody:
    def test_get_body_should_strip_frontmatter(self) -> None:
        parser = _make_parser()
        content = "---\ntitle: Test\n---\n\nBody text here."

        body = parser.get_body(content)
        assert "title:" not in body
        assert "Body text here." in body

    def test_get_body_should_return_full_content_without_frontmatter(self) -> None:
        parser = _make_parser()
        content = "No frontmatter, just body."

        body = parser.get_body(content)
        assert body == content
