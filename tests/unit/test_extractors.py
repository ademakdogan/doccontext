from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from doccontext.extractors import (
    ExtractorError,
    MdExtractor,
    PdfExtractor,
    TxtExtractor,
    UnsupportedFileType,
    extract_text,
    get_extractor,
)


def _write_pdf(path: Path, pages: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for text in pages:
        c.setFont("Helvetica", 16)
        for i, line in enumerate(text.splitlines() or [text]):
            c.drawString(72, 720 - i * 22, line)
        c.showPage()
    c.save()


# -------- registry --------


def test_get_extractor_returns_correct_class() -> None:
    assert isinstance(get_extractor("pdf"), PdfExtractor)
    assert isinstance(get_extractor("txt"), TxtExtractor)
    assert isinstance(get_extractor("md"), MdExtractor)


def test_get_extractor_normalizes_extension() -> None:
    assert isinstance(get_extractor(".PDF"), PdfExtractor)
    assert isinstance(get_extractor("TXT"), TxtExtractor)


def test_unknown_file_type_raises_unsupported() -> None:
    with pytest.raises(UnsupportedFileType):
        get_extractor("docx")


# -------- txt --------


def test_txt_extracts_utf8_text(tmp_path: Path) -> None:
    p = tmp_path / "sample.txt"
    p.write_text("hello world\nsecond line\n", encoding="utf-8")
    assert extract_text(p, "txt") == "hello world\nsecond line\n"


def test_txt_falls_back_on_bad_bytes(tmp_path: Path) -> None:
    p = tmp_path / "bad.txt"
    p.write_bytes(b"ok \xff\xfe broken")
    out = extract_text(p, "txt")
    assert "ok" in out and "broken" in out  # replacement chars fill the bad bytes


def test_txt_raises_extractor_error_when_missing(tmp_path: Path) -> None:
    with pytest.raises(ExtractorError):
        extract_text(tmp_path / "nope.txt", "txt")


# -------- md --------


def test_md_preserves_markdown(tmp_path: Path) -> None:
    content = "# Title\n\nParagraph with **bold**.\n\n- item 1\n- item 2\n"
    p = tmp_path / "sample.md"
    p.write_text(content, encoding="utf-8")
    assert extract_text(p, "md") == content


# -------- pdf --------


def test_pdf_single_page_text_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "one.pdf"
    _write_pdf(p, ["Hello PDF world"])
    out = extract_text(p, "pdf")
    assert "Hello PDF world" in out


def test_pdf_multi_page_joins_with_blank_line(tmp_path: Path) -> None:
    p = tmp_path / "two.pdf"
    _write_pdf(p, ["Alpha page", "Beta page"])
    out = extract_text(p, "pdf")
    assert "Alpha page" in out
    assert "Beta page" in out
    # Pages separated by at least one blank line so the chunker sees paragraph breaks.
    assert "\n\n" in out


def test_pdf_bad_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not actually a pdf")
    with pytest.raises(ExtractorError):
        extract_text(p, "pdf")


def test_pdf_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ExtractorError):
        extract_text(tmp_path / "missing.pdf", "pdf")
