import hashlib
import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Deterministic, dependency-free embedder for fast tests."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(text.encode()).digest()
            raw = [seed[i % len(seed)] / 255.0 for i in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            vectors.append([v / norm for v in raw])
        return vectors


class BGEM3Embedder:
    """Real BGE-M3 dense embedder via FlagEmbedding (fp16; device auto-selected by FlagEmbedding). Lazily loaded."""

    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self.model_name, use_fp16=True)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        out = model.encode(texts, return_dense=True, return_sparse=False, return_colbert_vecs=False)
        return [list(map(float, v)) for v in out["dense_vecs"]]
