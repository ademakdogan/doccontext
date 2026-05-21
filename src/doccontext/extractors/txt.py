from __future__ import annotations

from pathlib import Path

from doccontext.extractors.base import Extractor, ExtractorError


class TxtExtractor(Extractor):
    file_type = "txt"

    def extract(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Fall back to permissive decode; bytes that fail are replaced.
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise ExtractorError(f"failed to read {path}: {e}") from e
