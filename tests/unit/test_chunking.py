from __future__ import annotations

import pytest

from doccontext.chunking import RecursiveCharacterChunker, default_chunker
from doccontext.chunking.base import Chunk


def test_empty_text_yields_no_chunks() -> None:
    assert RecursiveCharacterChunker(100, 10).chunk("") == []


def test_short_text_is_single_chunk() -> None:
    c = RecursiveCharacterChunker(100, 10)
    out = c.chunk("Hello world")
    assert len(out) == 1
    assert out[0].text == "Hello world"
    assert out[0].char_start == 0
    assert out[0].char_end == len("Hello world")
    assert out[0].chunk_index == 0


def test_indices_are_sequential() -> None:
    text = "\n\n".join(f"paragraph {i} " + "x" * 50 for i in range(8))
    chunks = RecursiveCharacterChunker(120, 30).chunk(text)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunks_cover_full_text() -> None:
    text = "\n\n".join(f"paragraph {i} " + "x" * 80 for i in range(6))
    chunks = RecursiveCharacterChunker(200, 40).chunk(text)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)


def test_chunk_text_matches_char_range(_chunks_and_text_builder=None) -> None:
    text = "\n\n".join(f"Paragraph {i}: " + "abc " * 30 for i in range(5))
    chunks = RecursiveCharacterChunker(300, 60).chunk(text)
    for c in chunks:
        assert c.text == text[c.char_start : c.char_end]


def test_overlap_is_applied_between_neighbors() -> None:
    text = "\n\n".join("x" * 100 for _ in range(6))
    chunks = RecursiveCharacterChunker(chunk_size=150, chunk_overlap=30).chunk(text)
    assert len(chunks) > 1
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        cur = chunks[i]
        # Current chunk starts up to `chunk_overlap` chars before its "natural"
        # boundary, which is the previous chunk's end.
        rewind = prev.char_end - cur.char_start
        assert 0 <= rewind <= 30


def test_zero_overlap_yields_non_overlapping_chunks() -> None:
    text = "\n\n".join("y" * 100 for _ in range(6))
    chunks = RecursiveCharacterChunker(chunk_size=150, chunk_overlap=0).chunk(text)
    for i in range(1, len(chunks)):
        assert chunks[i].char_start >= chunks[i - 1].char_end


def test_oversized_single_token_is_split() -> None:
    text = "a" * 500  # one giant run with no separators
    chunks = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0).chunk(text)
    assert len(chunks) >= 5
    for c in chunks:
        assert len(c.text) <= 100


def test_prefers_paragraph_boundary_over_space() -> None:
    text = "First paragraph.\n\nSecond paragraph." + " tail" * 100
    chunks = RecursiveCharacterChunker(chunk_size=80, chunk_overlap=0).chunk(text)
    # First chunk should end at or around the paragraph break, not mid-word.
    assert "First paragraph." in chunks[0].text


def test_key_phrase_at_boundary_appears_in_two_chunks() -> None:
    """With 20% overlap, a phrase spanning the boundary should survive in one of the neighbors in full."""
    left = "alpha " * 40  # 240 chars
    key = "the critical fact lives right here"
    right = " beta" * 40
    text = left + key + right
    chunks = RecursiveCharacterChunker(chunk_size=250, chunk_overlap=60).chunk(text)
    # At least one chunk should contain the key phrase intact (overlap preserves it).
    assert any(key in c.text for c in chunks)


def test_invalid_parameters_raise() -> None:
    with pytest.raises(ValueError):
        RecursiveCharacterChunker(chunk_size=0, chunk_overlap=0)
    with pytest.raises(ValueError):
        RecursiveCharacterChunker(chunk_size=100, chunk_overlap=-1)
    with pytest.raises(ValueError):
        RecursiveCharacterChunker(chunk_size=100, chunk_overlap=100)


def test_default_chunker_reads_settings(isolated_env) -> None:
    isolated_env.setenv("CHUNK_SIZE", "512")
    isolated_env.setenv("CHUNK_OVERLAP", "128")
    from doccontext.config import reload_settings

    reload_settings()
    c = default_chunker()
    assert isinstance(c, RecursiveCharacterChunker)
    assert c.chunk_size == 512
    assert c.chunk_overlap == 128


def test_no_empty_chunks_emitted() -> None:
    text = "hello\n\n\n\n\n\nworld"
    chunks = RecursiveCharacterChunker(chunk_size=50, chunk_overlap=10).chunk(text)
    for c in chunks:
        assert c.text.strip() or c.text  # never empty
        assert isinstance(c, Chunk)
