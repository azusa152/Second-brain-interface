"""Performance tests for the indexing pipeline.

These tests use a synthetic vault and mock the embedding + Qdrant layers
to measure parsing/chunking throughput without network dependencies.
"""

import os
import time
from unittest.mock import MagicMock

import pytest

from backend.application.index_service import IndexService
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.vault_file_map import VaultFileMap
from tests.fixtures.generate_test_vault import generate_vault

_PERF_VAULT_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "perf_vault")
_PERF_NOTE_COUNT = 100


@pytest.fixture(scope="module", autouse=True)
def perf_vault() -> str:
    """Generate a 100-note vault once for the performance test module."""
    if not os.path.exists(_PERF_VAULT_DIR):
        generate_vault(_PERF_VAULT_DIR, _PERF_NOTE_COUNT)
    return _PERF_VAULT_DIR


def _make_perf_service(vault_path: str) -> tuple[IndexService, MagicMock]:
    """Create IndexService with mocked external deps for perf testing."""
    vault_file_map = VaultFileMap(vault_path)
    parser = MarkdownParser(vault_file_map)
    chunker = Chunker()

    mock_embedder = MagicMock()
    mock_embedder.embed_batch.side_effect = lambda texts: [[0.0] * 384 for _ in texts]
    mock_embedder.embed_batch_sparse.side_effect = lambda texts: [
        MagicMock(indices=[1], values=[0.5]) for _ in texts
    ]

    mock_qdrant = MagicMock()
    mock_qdrant.is_healthy.return_value = True
    mock_qdrant.get_chunks_count.return_value = 0
    mock_qdrant.get_indexed_note_paths.return_value = set()

    service = IndexService(
        vault_path=vault_path,
        parser=parser,
        chunker=chunker,
        embedder=mock_embedder,
        qdrant_adapter=mock_qdrant,
        vault_file_map=vault_file_map,
    )
    service.initialize()
    return service, mock_qdrant


class TestRebuildPerformance:
    def test_rebuild_100_notes_should_complete_under_30_seconds(
        self, perf_vault: str
    ) -> None:
        service, mock_qdrant = _make_perf_service(perf_vault)

        start = time.time()
        result = service.rebuild_index()
        elapsed = time.time() - start

        assert result is not None
        assert result.status == "success"
        assert result.notes_indexed == _PERF_NOTE_COUNT
        assert result.chunks_created > 0
        assert elapsed < 30.0, f"Rebuild took {elapsed:.1f}s (limit: 30s)"

    def test_rebuild_should_create_reasonable_chunk_count(
        self, perf_vault: str
    ) -> None:
        service, _ = _make_perf_service(perf_vault)
        result = service.rebuild_index()

        assert result is not None
        # Each note should produce at least 1 chunk
        assert result.chunks_created >= _PERF_NOTE_COUNT
        # But not an absurd number (sanity check)
        assert result.chunks_created < _PERF_NOTE_COUNT * 50
