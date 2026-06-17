"""Prompt templates for the two-stage RAG flow.

Design invariant: the user's question is always the FIRST message in both
stages so provider prompt caches can hit on repeat queries with the same
user question.
"""

from __future__ import annotations

from collections.abc import Sequence

from doccontext.llm.base import Message
from doccontext.models.chunk import RetrievedChunk

ROUTER_SYSTEM_INSTRUCTION = """\
You are a routing classifier for a retrieval-augmented QA system.

Classify the user's question into exactly one of:

- FULL_DOC: the answer requires understanding the whole document
  (summarise, outline, overall tone, structure, cross-section comparison).
- SECTION: the answer is a specific fact, passage, or quote that lives
  in a small part of the document.

Be conservative: default to SECTION unless the question clearly needs
whole-document reasoning.

Respond with STRICT JSON on a single line and nothing else, matching:
{"route": "FULL_DOC" | "SECTION", "confidence": <float between 0 and 1>}
"""


ANSWER_SECTION_SYSTEM_INSTRUCTION = """\
You are a retrieval-augmented assistant. Answer the user's question using
ONLY the retrieved chunks provided below. If the chunks do not contain
enough information, say so honestly.

Cite the chunk_id of every chunk you used.

Respond with STRICT JSON on a single line and nothing else, matching:
{
  "answer": <string>,
  "citations": [
    {"chunk_id": <string>, "document_id": <string>, "quote": <string>}
  ]
}
"""


ANSWER_FULL_DOC_SYSTEM_INSTRUCTION = """\
You are an assistant answering questions over one or more full documents.
Use the complete documents provided below; you may summarise, compare, and
synthesize across sections.

If a claim leans on a specific passage, include it as a citation with the
document_id (chunk_id may be empty).

Respond with STRICT JSON on a single line and nothing else, matching:
{
  "answer": <string>,
  "citations": [
    {"chunk_id": <string>, "document_id": <string>, "quote": <string>}
  ]
}
"""


def format_chunks(chunks: Sequence[RetrievedChunk]) -> str:
    """Render retrieved chunks as a deterministic, model-readable block."""
    blocks: list[str] = []
    for c in chunks:
        blocks.append(
            f"--- CHUNK chunk_id={c.chunk_id} document_id={c.document_id} "
            f"chunk_index={c.chunk_index} score={c.score:.4f} ---\n{c.text}"
        )
    return "\n\n".join(blocks)


def format_full_documents(docs: Sequence[tuple[str, str]]) -> str:
    """Render (document_id, full_text) pairs as a deterministic block."""
    blocks: list[str] = []
    for document_id, text in docs:
        blocks.append(f"--- DOCUMENT document_id={document_id} ---\n{text}")
    return "\n\n".join(blocks)


def build_router_messages(user_prompt: str) -> list[Message]:
    """Stage-1 messages: user question first so the cache prefix stays stable."""
    return [
        Message(role="user", content=user_prompt),
        Message(role="system", content=ROUTER_SYSTEM_INSTRUCTION),
    ]


def build_section_answer_messages(
    *,
    user_prompt: str,
    history: Sequence[Message] = (),
    chunks: Sequence[RetrievedChunk],
) -> list[Message]:
    """Stage-2 messages for the SECTION path.

    Order: user prompt → history (no chunks) → system instruction → chunks.
    """
    return [
        Message(role="user", content=user_prompt),
        *history,
        Message(role="system", content=ANSWER_SECTION_SYSTEM_INSTRUCTION),
        Message(role="system", content=f"Retrieved chunks:\n\n{format_chunks(chunks)}"),
    ]


def build_full_doc_answer_messages(
    *,
    user_prompt: str,
    history: Sequence[Message] = (),
    documents: Sequence[tuple[str, str]],
) -> list[Message]:
    """Stage-2 messages for the FULL_DOC path."""
    return [
        Message(role="user", content=user_prompt),
        *history,
        Message(role="system", content=ANSWER_FULL_DOC_SYSTEM_INSTRUCTION),
        Message(
            role="system",
            content=f"Full documents:\n\n{format_full_documents(documents)}",
        ),
    ]
