"""Unit tests for QdrantAdapter infrastructure behavior."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Filter

from backend.domain.models import NoteChunk
from backend.infrastructure.embedding import SparseVector
from backend.infrastructure.qdrant_adapter import QdrantAdapter


def _make_adapter() -> QdrantAdapter:
    """Create a QdrantAdapter with a mocked client (no real connection)."""
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter._legacy_prefixes_cache = None
    return adapter


class TestHybridSearchFilterPropagation:
    def test_hybrid_search_should_pass_query_filter_to_qdrant(self) -> None:
        adapter = _make_adapter()
        adapter.client.query_points.return_value = SimpleNamespace(
            points=[
                SimpleNamespace(
                    payload={
                        "chunk_id": "notes/n1.md#chunk0",
                        "note_path": "notes/n1.md",
                        "note_title": "N1",
                        "content": "hello",
                        "heading_context": "H1",
                        "tags": ["devops"],
                    },
                    score=0.8,
                )
            ]
        )
        query_filter = Filter()

        adapter.hybrid_search(
            query_vector=[0.1, 0.2],
            sparse_vector=SparseVector(indices=[1], values=[0.3]),
            top_k=5,
            query_filter=query_filter,
        )

        kwargs = adapter.client.query_points.call_args.kwargs
        assert kwargs["query_filter"] == query_filter
        assert kwargs["prefetch"][0].filter == query_filter
        assert kwargs["prefetch"][1].filter == query_filter


class TestPayloadIndexCreation:
    def test_ensure_payload_indexes_should_create_all_indexes(self) -> None:
        adapter = _make_adapter()

        adapter._ensure_payload_indexes()

        assert adapter.client.create_payload_index.call_count == 4
        field_names = [
            call.kwargs["field_name"] for call in adapter.client.create_payload_index.call_args_list
        ]
        assert field_names == ["tags", "note_path", "note_path_prefixes", "last_modified"]

    def test_ensure_payload_indexes_should_ignore_409_conflict(self) -> None:
        adapter = _make_adapter()
        err = UnexpectedResponse(
            status_code=409, reason_phrase="Conflict", content=b"already exists", headers={}
        )
        adapter.client.create_payload_index.side_effect = err

        adapter._ensure_payload_indexes()

        assert adapter.client.create_payload_index.call_count == 4

    def test_ensure_payload_indexes_should_raise_non_409_unexpected_response(self) -> None:
        adapter = _make_adapter()
        err = UnexpectedResponse(
            status_code=500, reason_phrase="Internal Server Error", content=b"boom", headers={}
        )
        adapter.client.create_payload_index.side_effect = err

        with pytest.raises(UnexpectedResponse):
            adapter._ensure_payload_indexes()


class TestChunkPayloadPrefixes:
    def test_bulk_upsert_chunks_should_store_note_path_prefixes(self) -> None:
        adapter = _make_adapter()
        chunk = NoteChunk(
            chunk_id="projects/infra/plan.md#chunk0",
            note_path="projects/infra/plan.md",
            content="migration plan",
            chunk_index=0,
            note_title="Plan",
            tags=["#devops"],
            last_modified=datetime(2025, 1, 1, tzinfo=UTC),
            embedding=[0.1, 0.2],
        )
        sparse_vectors = [SparseVector(indices=[1, 2], values=[0.3, 0.4])]

        adapter.bulk_upsert_chunks([chunk], sparse_vectors=sparse_vectors)

        upsert_kwargs = adapter.client.upsert.call_args.kwargs
        payload = upsert_kwargs["points"][0].payload
        assert payload["note_path_prefixes"] == ["projects/", "projects/infra/"]


class TestLegacyPrefixDetection:
    def test_should_return_true_when_subfolder_chunk_lacks_prefixes(self) -> None:
        adapter = _make_adapter()
        adapter.client.scroll.return_value = (
            [
                SimpleNamespace(
                    payload={"note_path": "projects/plan.md", "note_path_prefixes": None}
                ),
            ],
            None,
        )

        assert adapter.has_legacy_chunks_without_prefixes() is True

    def test_should_return_true_when_prefixes_field_missing(self) -> None:
        adapter = _make_adapter()
        adapter.client.scroll.return_value = (
            [
                SimpleNamespace(payload={"note_path": "projects/plan.md"}),
            ],
            None,
        )

        assert adapter.has_legacy_chunks_without_prefixes() is True

    def test_should_return_false_when_all_chunks_have_prefixes(self) -> None:
        adapter = _make_adapter()
        adapter.client.scroll.return_value = (
            [
                SimpleNamespace(
                    payload={
                        "note_path": "projects/plan.md",
                        "note_path_prefixes": ["projects/"],
                    }
                ),
            ],
            None,
        )

        assert adapter.has_legacy_chunks_without_prefixes() is False

    def test_should_return_false_when_root_note_lacks_prefixes(self) -> None:
        """Root-level notes have no folder hierarchy, so missing prefixes is expected."""
        adapter = _make_adapter()
        adapter.client.scroll.return_value = (
            [
                SimpleNamespace(payload={"note_path": "inbox.md", "note_path_prefixes": []}),
            ],
            None,
        )

        assert adapter.has_legacy_chunks_without_prefixes() is False

    def test_should_return_false_when_collection_is_empty(self) -> None:
        adapter = _make_adapter()
        adapter.client.scroll.return_value = ([], None)

        assert adapter.has_legacy_chunks_without_prefixes() is False

    def test_should_return_true_when_scroll_raises(self) -> None:
        """Connection failures are treated as 'legacy data may exist' for safety."""
        adapter = _make_adapter()
        adapter.client.scroll.side_effect = RuntimeError("connection lost")

        assert adapter.has_legacy_chunks_without_prefixes() is True

    def test_should_scroll_all_pages_to_find_legacy_chunk(self) -> None:
        adapter = _make_adapter()
        adapter.client.scroll.side_effect = [
            (
                [SimpleNamespace(payload={"note_path": "a/ok.md", "note_path_prefixes": ["a/"]})],
                "page2",
            ),
            (
                [SimpleNamespace(payload={"note_path": "b/legacy.md", "note_path_prefixes": None})],
                None,
            ),
        ]

        assert adapter.has_legacy_chunks_without_prefixes() is True
        assert adapter.client.scroll.call_count == 2


class TestLegacyPrefixCache:
    def test_should_cache_result_after_first_call(self) -> None:
        adapter = _make_adapter()
        adapter.client.scroll.return_value = ([], None)

        adapter.has_legacy_chunks_without_prefixes()
        adapter.has_legacy_chunks_without_prefixes()

        assert adapter.client.scroll.call_count == 1

    def test_mark_prefixes_current_should_clear_cache(self) -> None:
        adapter = _make_adapter()
        adapter.client.scroll.return_value = (
            [SimpleNamespace(payload={"note_path": "a/b.md", "note_path_prefixes": None})],
            None,
        )

        assert adapter.has_legacy_chunks_without_prefixes() is True
        adapter.mark_prefixes_current()
        assert adapter.has_legacy_chunks_without_prefixes() is False
        # scroll not called again — cache was set to False by mark_prefixes_current
        assert adapter.client.scroll.call_count == 1
