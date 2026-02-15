import numpy as np
from fastembed import TextEmbedding

from backend.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingService:
    """Thin wrapper around fastembed for text-to-vector conversion."""

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model: TextEmbedding | None = None
        self._model_name = model_name

    def _ensure_loaded(self) -> None:
        """Lazy-load the model on first use."""
        if self._model is None:
            logger.info("Loading embedding model: %s", self._model_name)
            self._model = TextEmbedding(model_name=self._model_name)

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""
        self._ensure_loaded()
        assert self._model is not None
        results = list(self._model.embed([text]))
        return self._to_list(results[0])

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts efficiently (batched)."""
        if not texts:
            return []
        self._ensure_loaded()
        assert self._model is not None
        results = list(self._model.embed(texts))
        return [self._to_list(v) for v in results]

    @staticmethod
    def _to_list(vector: np.ndarray | list[float]) -> list[float]:
        """Convert numpy array to plain list of floats."""
        if isinstance(vector, np.ndarray):
            return vector.tolist()
        return list(vector)
