from __future__ import annotations

from doccontext.extractors.txt import TxtExtractor


class MdExtractor(TxtExtractor):
    """Markdown is read verbatim as UTF-8 text; chunking preserves headings."""

    file_type = "md"
