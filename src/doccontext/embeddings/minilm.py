from __future__ import annotations

from collections.abc import Sequence

from doccontext.embeddings.base import Embedder


class MiniLMEmbedder(Embedder):
    """sentence-transformers/all-MiniLM-L6-v2 — 384-dim, normalized output."""

    name = "all-MiniLM-L6-v2"
    dim = 384
    model_id = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self) -> None:
        # Lazy import so `import doccontext` stays fast and CLI-only tests don't
        # pay the model-load cost.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_id)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()
