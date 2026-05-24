from __future__ import annotations

from collections.abc import Iterator

from doccontext.chunking.base import Chunk, Chunker

# Ordered from coarsest to finest boundary — the same hierarchy LlamaIndex /
# LangChain use. Every separator is tried in turn so we always cut on the
# most natural boundary that fits.
_DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


class RecursiveCharacterChunker(Chunker):
    """Character-based recursive chunker with overlap.

    The algorithm:

    1. If the input is <= chunk_size, return a single chunk.
    2. Otherwise find the coarsest separator that appears in the text and
       split on it.
    3. Greedily re-assemble the pieces into windows of <= chunk_size.
    4. Emit those windows with a trailing overlap of ``chunk_overlap``
       characters from the previous window, so information at chunk
       boundaries is preserved across neighbors.

    char_start / char_end indices refer to positions in the original text,
    which matters for citations + deduplicated source spans.
    """

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        separators: tuple[str, ...] = _DEFAULT_SEPARATORS,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be >= 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be < chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators

    # -- public API --

    def chunk(self, text: str) -> list[Chunk]:
        if not text:
            return []
        windows = self._build_windows(text)
        return self._add_overlap(windows, text)

    # -- internal --

    def _pick_separator(self, text: str) -> str:
        for sep in self.separators:
            if sep == "" or sep in text:
                return sep
        return ""

    def _split_with_positions(self, text: str, sep: str) -> list[tuple[int, str]]:
        """Split ``text`` on ``sep`` keeping each piece's start index.

        When ``sep`` is empty we fall back to per-character splitting so we
        can still honor chunk_size for pathological inputs (very long words,
        etc.).
        """
        if sep == "":
            return [(i, ch) for i, ch in enumerate(text)]
        pieces: list[tuple[int, str]] = []
        start = 0
        while True:
            idx = text.find(sep, start)
            if idx == -1:
                pieces.append((start, text[start:]))
                return pieces
            end = idx + len(sep)
            pieces.append((start, text[start:end]))
            start = end

    def _build_windows(self, text: str) -> list[tuple[int, int]]:
        """Greedy assemble pieces into (char_start, char_end) windows."""
        sep = self._pick_separator(text)
        pieces = self._split_with_positions(text, sep)

        windows: list[tuple[int, int]] = []
        cur_start: int | None = None
        cur_end: int = 0
        cur_len: int = 0

        for piece_start, piece_text in pieces:
            if not piece_text:
                continue
            piece_len = len(piece_text)
            if cur_start is None:
                cur_start = piece_start
                cur_end = piece_start + piece_len
                cur_len = piece_len
                # A single piece already bigger than chunk_size needs its own
                # recursive pass on a finer separator.
                if cur_len > self.chunk_size:
                    windows.extend(self._expand_oversized(text, cur_start, cur_end, sep))
                    cur_start, cur_end, cur_len = None, 0, 0
                continue

            if cur_len + piece_len <= self.chunk_size:
                cur_end = piece_start + piece_len
                cur_len += piece_len
            else:
                windows.append((cur_start, cur_end))
                cur_start = piece_start
                cur_end = piece_start + piece_len
                cur_len = piece_len
                if cur_len > self.chunk_size:
                    windows.extend(self._expand_oversized(text, cur_start, cur_end, sep))
                    cur_start, cur_end, cur_len = None, 0, 0

        if cur_start is not None:
            windows.append((cur_start, cur_end))

        return windows

    def _expand_oversized(
        self, text: str, start: int, end: int, parent_sep: str
    ) -> list[tuple[int, int]]:
        """Recurse on a single oversized piece using the next finer separator."""
        try:
            idx = self.separators.index(parent_sep)
            finer = self.separators[idx + 1 :]
        except ValueError:
            finer = ("",)
        if not finer:
            finer = ("",)

        sub = RecursiveCharacterChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=0,  # overlap is added once at the outermost pass
            separators=finer,
        )
        sub_chunks = sub.chunk(text[start:end])
        return [(start + c.char_start, start + c.char_end) for c in sub_chunks]

    def _add_overlap(self, windows: list[tuple[int, int]], text: str) -> list[Chunk]:
        out: list[Chunk] = []
        prev_end = 0
        for i, (ws, we) in enumerate(windows):
            if i == 0 or self.chunk_overlap == 0:
                start = ws
            else:
                start = max(0, min(prev_end, ws) - self.chunk_overlap)
            # Never emit an empty chunk; never let the overlap make the next
            # chunk strictly a subset of its predecessor.
            if out and start <= out[-1].char_start and we <= out[-1].char_end:
                continue
            chunk_text = text[start:we]
            if not chunk_text:
                continue
            out.append(
                Chunk(
                    text=chunk_text,
                    chunk_index=len(out),
                    char_start=start,
                    char_end=we,
                )
            )
            prev_end = we
        return out


__all__ = ["Chunk", "Chunker", "RecursiveCharacterChunker"]
