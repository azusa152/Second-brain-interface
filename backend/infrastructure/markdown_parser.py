import os
import re
from datetime import datetime, timezone

import yaml

from backend.domain.models import NoteMetadata, WikiLink
from backend.infrastructure.vault_file_map import VaultFileMap
from backend.logging_config import get_logger

logger = get_logger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z][a-zA-Z0-9_/-]*)\b")
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"\*(.+?)\*")


class MarkdownParser:
    """Parse .md files, extract structured data, resolve wikilinks."""

    def __init__(self, vault_file_map: VaultFileMap) -> None:
        self._file_map = vault_file_map

    def parse(
        self, file_path: str, content: str, last_modified: datetime | None = None
    ) -> tuple[NoteMetadata, list[WikiLink]]:
        """Parse markdown file and return metadata + extracted links."""
        frontmatter, body = self._extract_frontmatter(content)
        title = self._extract_title(file_path, frontmatter, body)
        tags = self._extract_tags(frontmatter, body)
        links = self._extract_wikilinks(file_path, body)
        clean_text = self._strip_formatting(body)
        word_count = len(clean_text.split())

        if last_modified is None:
            last_modified = datetime.now(tz=timezone.utc)

        metadata = NoteMetadata(
            file_path=file_path,
            title=title,
            last_modified=last_modified,
            frontmatter=frontmatter,
            tags=tags,
            word_count=word_count,
        )
        return metadata, links

    def get_body(self, content: str) -> str:
        """Return the markdown body (everything after frontmatter)."""
        match = _FRONTMATTER_RE.match(content)
        if match:
            return content[match.end() :]
        return content

    def _extract_frontmatter(self, content: str) -> tuple[dict, str]:
        """Extract YAML frontmatter and return (frontmatter_dict, body)."""
        match = _FRONTMATTER_RE.match(content)
        if not match:
            return {}, content

        raw_yaml = match.group(1)
        body = content[match.end() :]
        try:
            frontmatter = yaml.safe_load(raw_yaml)
            if not isinstance(frontmatter, dict):
                return {}, body
            return frontmatter, body
        except yaml.YAMLError:
            logger.warning("Failed to parse frontmatter in note")
            return {}, body

    def _extract_title(
        self, file_path: str, frontmatter: dict, body: str
    ) -> str:
        """Extract title from frontmatter, first H1, or filename."""
        if "title" in frontmatter:
            return str(frontmatter["title"])

        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                return stripped.lstrip("# ").strip()

        return os.path.splitext(os.path.basename(file_path))[0]

    def _extract_tags(self, frontmatter: dict, body: str) -> list[str]:
        """Extract tags from frontmatter and inline #tags."""
        tags: set[str] = set()

        # Frontmatter tags
        fm_tags = frontmatter.get("tags", [])
        if isinstance(fm_tags, list):
            tags.update(str(t) for t in fm_tags)
        elif isinstance(fm_tags, str):
            tags.add(fm_tags)

        # Inline #tags (skip code blocks)
        clean = _CODE_BLOCK_RE.sub("", body)
        clean = _INLINE_CODE_RE.sub("", clean)
        for match in _TAG_RE.finditer(clean):
            tags.add(match.group(1))

        return sorted(tags)

    def _extract_wikilinks(
        self, source_path: str, body: str
    ) -> list[WikiLink]:
        """Extract and resolve [[wikilinks]] from body text."""
        # Skip code blocks
        clean = _CODE_BLOCK_RE.sub("", body)
        clean = _INLINE_CODE_RE.sub("", clean)

        links: list[WikiLink] = []
        seen: set[str] = set()

        for match in _WIKILINK_RE.finditer(clean):
            raw = match.group(1)
            # Handle [[target|alias]] syntax
            link_text = raw.split("|")[0].strip()

            if link_text in seen:
                continue
            seen.add(link_text)

            resolved = self._file_map.resolve(link_text)
            links.append(
                WikiLink(
                    source_path=source_path,
                    link_text=link_text,
                    resolved_target_path=resolved,
                )
            )
        return links

    def _strip_formatting(self, text: str) -> str:
        """Strip markdown formatting for clean text."""
        text = _CODE_BLOCK_RE.sub("", text)
        text = _INLINE_CODE_RE.sub("", text)
        text = _BOLD_RE.sub(r"\1", text)
        text = _ITALIC_RE.sub(r"\1", text)
        text = _WIKILINK_RE.sub(r"\1", text)
        return text
