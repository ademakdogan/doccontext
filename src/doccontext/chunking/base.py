from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Chunk:
    text: str
    chunk_index: int
    char_start: int
    char_end: int


class Chunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> Iterable[Chunk]:
        ...
