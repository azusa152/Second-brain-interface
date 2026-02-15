import numpy as np
from fastembed import SparseTextEmbedding, TextEmbedding

from backend.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_SPARSE_MODEL = "Qdrant/bm25"


class SparseVector:
    """Lightweight container for sparse vector indices and values."""

    __slots__ = ("indices", "values")

    def __init__(self, indices: list[int], values: list[float]) -> None:
        self.indices = indices
        self.values = values


class EmbeddingService:
    """Thin wrapper around fastembed for text-to-vector conversion."""

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        sparse_model_name: str = _DEFAULT_SPARSE_MODEL,
    ) -> None:
        self._model: TextEmbedding | None = None
        self._model_name = model_name
        self._sparse_model: SparseTextEmbedding | None = None
        self._sparse_model_name = sparse_model_name

    def _ensure_loaded(self) -> None:
        """Lazy-load the dense model on first use."""
        if self._model is None:
            logger.info("Loading embedding model: %s", self._model_name)
            self._model = TextEmbedding(model_name=self._model_name)

    def _ensure_sparse_loaded(self) -> None:
        """Lazy-load the sparse model on first use."""
        if self._sparse_model is None:
            logger.info("Loading sparse model: %s", self._sparse_model_name)
            self._sparse_model = SparseTextEmbedding(
                model_name=self._sparse_model_name,
            )

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string (dense)."""
        self._ensure_loaded()
        assert self._model is not None
        results = list(self._model.embed([text]))
        return self._to_list(results[0])

    def embed_text_sparse(self, text: str) -> SparseVector:
        """Embed a single text string (sparse BM25)."""
        self._ensure_sparse_loaded()
        assert self._sparse_model is not None
        results = list(self._sparse_model.embed([text]))
        raw = results[0]
        return SparseVector(
            indices=raw.indices.tolist(),
            values=raw.values.tolist(),
        )

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts efficiently (dense, batched)."""
        if not texts:
            return []
        self._ensure_loaded()
        assert self._model is not None
        results = list(self._model.embed(texts))
        return [self._to_list(v) for v in results]

    def embed_batch_sparse(self, texts: list[str]) -> list[SparseVector]:
        """Embed multiple texts (sparse BM25, batched)."""
        if not texts:
            return []
        self._ensure_sparse_loaded()
        assert self._sparse_model is not None
        results = list(self._sparse_model.embed(texts))
        return [
            SparseVector(indices=r.indices.tolist(), values=r.values.tolist())
            for r in results
        ]

    @staticmethod
    def _to_list(vector: np.ndarray | list[float]) -> list[float]:
        """Convert numpy array to plain list of floats."""
        if isinstance(vector, np.ndarray):
            return vector.tolist()
        return list(vector)
