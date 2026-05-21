from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ExtractorError(Exception):
    """Raised when a document cannot be extracted."""


class UnsupportedFileType(ExtractorError):
    """Raised when no extractor is registered for the requested file type."""


class Extractor(ABC):
    """Turns a document file on disk into plain UTF-8 text.

    Implementations MUST be deterministic for a given input file so chunk
    boundaries remain stable across reindexes.
    """

    file_type: str

    @abstractmethod
    def extract(self, path: Path) -> str:
        """Return the document's full text. Raises ExtractorError on failure."""
