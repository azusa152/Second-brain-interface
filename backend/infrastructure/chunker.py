import re

from backend.domain.constants import CHUNK_OVERLAP, CHUNK_SIZE
from backend.domain.models import NoteChunk
from backend.logging_config import get_logger

logger = get_logger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


class Chunker:
    """Split long notes into semantically coherent chunks."""

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(self, note_path: str, content: str) -> list[NoteChunk]:
        """Split content into chunks for indexing."""
        sections = self._split_by_headings(content)
        chunks: list[NoteChunk] = []

        for heading_context, section_text in sections:
            section_text = section_text.strip()
            if not section_text:
                continue

            if len(section_text) <= self._chunk_size:
                chunks.append(
                    NoteChunk(
                        chunk_id=f"{note_path}#chunk{len(chunks)}",
                        note_path=note_path,
                        content=section_text,
                        chunk_index=len(chunks),
                        heading_context=heading_context,
                    )
                )
            else:
                sub_chunks = self._split_fixed_size(section_text)
                for sub in sub_chunks:
                    chunks.append(
                        NoteChunk(
                            chunk_id=f"{note_path}#chunk{len(chunks)}",
                            note_path=note_path,
                            content=sub,
                            chunk_index=len(chunks),
                            heading_context=heading_context,
                        )
                    )

        return chunks

    def _split_by_headings(self, content: str) -> list[tuple[str | None, str]]:
        """Split content by headings, returning (heading_hierarchy, text) pairs."""
        lines = content.split("\n")
        # Level-indexed: heading_by_level[1] = "Top", heading_by_level[2] = "Sub"
        heading_by_level: dict[int, str] = {}
        sections: list[tuple[str | None, str]] = []
        current_lines: list[str] = []

        for line in lines:
            match = _HEADING_RE.match(line)
            if match:
                # Flush current section
                if current_lines:
                    ctx = self._build_context(heading_by_level)
                    sections.append((ctx, "\n".join(current_lines)))
                    current_lines = []

                level = len(match.group(1))
                heading_text = match.group(2).strip()

                # Set this level and clear all deeper levels
                heading_by_level[level] = heading_text
                for deeper in list(heading_by_level):
                    if deeper > level:
                        del heading_by_level[deeper]
            else:
                current_lines.append(line)

        # Flush remaining content
        if current_lines:
            ctx = self._build_context(heading_by_level)
            sections.append((ctx, "\n".join(current_lines)))

        return sections

    @staticmethod
    def _build_context(heading_by_level: dict[int, str]) -> str | None:
        """Build 'H1 > H2 > H3' context string from level-indexed dict."""
        if not heading_by_level:
            return None
        return " > ".join(heading_by_level[lvl] for lvl in sorted(heading_by_level))

    def _split_fixed_size(self, text: str) -> list[str]:
        """Split long text into fixed-size chunks with overlap."""
        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = start + self._chunk_size
            chunk = text[start:end]

            if chunk.strip():
                chunks.append(chunk.strip())

            # Advance by (chunk_size - overlap)
            start += self._chunk_size - self._chunk_overlap

        return chunks
