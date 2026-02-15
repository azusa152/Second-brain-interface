from backend.infrastructure.chunker import Chunker


class TestChunkerBasic:
    def test_chunk_should_return_single_chunk_for_short_text(self) -> None:
        chunker = Chunker()
        content = "Short text that fits in one chunk."

        chunks = chunker.chunk("test.md", content)

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].chunk_id == "test.md#chunk0"
        assert chunks[0].note_path == "test.md"
        assert chunks[0].chunk_index == 0

    def test_chunk_should_return_empty_for_blank_content(self) -> None:
        chunker = Chunker()

        chunks = chunker.chunk("test.md", "")
        assert chunks == []

    def test_chunk_should_return_empty_for_whitespace_only(self) -> None:
        chunker = Chunker()

        chunks = chunker.chunk("test.md", "   \n\n  ")
        assert chunks == []


class TestHeadingSplitting:
    def test_chunk_should_split_by_headings(self) -> None:
        chunker = Chunker()
        content = "## Section A\n\nContent A.\n\n## Section B\n\nContent B."

        chunks = chunker.chunk("test.md", content)

        assert len(chunks) == 2
        assert "Content A" in chunks[0].content
        assert "Content B" in chunks[1].content

    def test_chunk_should_preserve_heading_hierarchy(self) -> None:
        chunker = Chunker()
        content = (
            "# Top\n\nIntro.\n"
            "## Middle\n\nMiddle text.\n"
            "### Bottom\n\nBottom text."
        )

        chunks = chunker.chunk("test.md", content)

        # Find the chunk with "Bottom text"
        bottom_chunk = [c for c in chunks if "Bottom text" in c.content][0]
        assert bottom_chunk.heading_context == "Top > Middle > Bottom"

    def test_chunk_should_handle_content_before_first_heading(self) -> None:
        chunker = Chunker()
        content = "Preamble text.\n\n## Section\n\nSection text."

        chunks = chunker.chunk("test.md", content)

        assert len(chunks) == 2
        assert "Preamble text" in chunks[0].content
        assert chunks[0].heading_context is None

    def test_chunk_should_track_heading_level_resets(self) -> None:
        chunker = Chunker()
        content = (
            "## A\n\nText A.\n"
            "### A1\n\nText A1.\n"
            "## B\n\nText B."
        )

        chunks = chunker.chunk("test.md", content)

        a1_chunk = [c for c in chunks if "Text A1" in c.content][0]
        assert a1_chunk.heading_context == "A > A1"

        b_chunk = [c for c in chunks if "Text B" in c.content][0]
        assert b_chunk.heading_context == "B"


class TestFixedSizeSplitting:
    def test_chunk_should_split_long_section_with_overlap(self) -> None:
        chunker = Chunker(chunk_size=50, chunk_overlap=10)
        long_text = "word " * 100  # ~500 chars

        chunks = chunker.chunk("test.md", long_text)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.content) <= 50

    def test_chunk_ids_should_be_sequential(self) -> None:
        chunker = Chunker(chunk_size=50, chunk_overlap=10)
        long_text = "word " * 100

        chunks = chunker.chunk("test.md", long_text)

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"test.md#chunk{i}"
            assert chunk.chunk_index == i
