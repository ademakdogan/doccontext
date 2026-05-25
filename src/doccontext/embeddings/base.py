from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence


class Embedder(ABC):
    """Turns text into fixed-dimension float vectors.

    Implementations MUST preserve input order and return one vector per input.
    Calls SHOULD be batched; the service layer may invoke ``embed`` with
    hundreds of chunks at once.
    """

    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
