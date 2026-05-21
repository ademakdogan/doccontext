from __future__ import annotations

from pathlib import Path

from doccontext.extractors.base import Extractor, ExtractorError, UnsupportedFileType
from doccontext.extractors.md import MdExtractor
from doccontext.extractors.pdf import PdfExtractor
from doccontext.extractors.txt import TxtExtractor

_REGISTRY: dict[str, type[Extractor]] = {
    "pdf": PdfExtractor,
    "txt": TxtExtractor,
    "md": MdExtractor,
}


def get_extractor(file_type: str) -> Extractor:
    key = file_type.lower().lstrip(".")
    try:
        cls = _REGISTRY[key]
    except KeyError as e:
        raise UnsupportedFileType(f"no extractor registered for file type {file_type!r}") from e
    return cls()


def extract_text(path: Path, file_type: str) -> str:
    return get_extractor(file_type).extract(Path(path))


__all__ = [
    "Extractor",
    "ExtractorError",
    "MdExtractor",
    "PdfExtractor",
    "TxtExtractor",
    "UnsupportedFileType",
    "extract_text",
    "get_extractor",
]
