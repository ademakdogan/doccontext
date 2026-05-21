from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from doccontext.extractors.base import Extractor, ExtractorError


class PdfExtractor(Extractor):
    """Readable-PDF extractor. Scanned / image-only PDFs produce empty text."""

    file_type = "pdf"

    def extract(self, path: Path) -> str:
        try:
            reader = PdfReader(str(path))
        except (PdfReadError, OSError) as e:
            raise ExtractorError(f"failed to open PDF {path}: {e}") from e

        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception as e:  # pypdf raises a variety of internal errors
                raise ExtractorError(f"failed to extract page text from {path}: {e}") from e
        # Join pages with a blank line so chunker can see page boundaries.
        return "\n\n".join(p.strip() for p in pages if p.strip())
