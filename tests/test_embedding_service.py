import numpy as np

from backend.infrastructure.embedding import EmbeddingService


class _FakeDenseModel:
    def __init__(self) -> None:
        self.last_inputs: list[str] = []

    def embed(self, texts: list[str]):
        self.last_inputs = texts
        for _ in texts:
            yield [0.1, 0.2, 0.3]


class _FakeSparse:
    def __init__(self, indices: list[int], values: list[float]) -> None:
        self.indices = np.array(indices)
        self.values = np.array(values)


class _FakeSparseModel:
    def __init__(self) -> None:
        self.last_inputs: list[str] = []

    def embed(self, texts: list[str]):
        self.last_inputs = texts
        for _ in texts:
            yield _FakeSparse(indices=[1, 2], values=[0.3, 0.2])


class TestDenseNormalization:
    def test_embed_text_should_apply_nfkc_normalization(self) -> None:
        service = EmbeddingService()
        fake = _FakeDenseModel()
        service._model = fake

        _ = service.embed_text("\uff21\uff22\uff23")

        assert fake.last_inputs == ["ABC"]

    def test_embed_batch_should_apply_nfkc_normalization(self) -> None:
        service = EmbeddingService()
        fake = _FakeDenseModel()
        service._model = fake

        _ = service.embed_batch(["\uff21\uff22\uff23", "\uff11\uff12\uff13"])

        assert fake.last_inputs == ["ABC", "123"]


class TestSparseNormalization:
    def test_embed_text_sparse_should_apply_nfkc_tokenization(self) -> None:
        service = EmbeddingService()
        fake = _FakeSparseModel()
        service._sparse_model = fake

        _ = service.embed_text_sparse("\uff21\uff22\uff23")

        assert fake.last_inputs == ["ABC"]
