from __future__ import annotations

from doccontext.llm.base import Message
from doccontext.llm.prompts import (
    ANSWER_FULL_DOC_SYSTEM_INSTRUCTION,
    ANSWER_SECTION_SYSTEM_INSTRUCTION,
    ROUTER_SYSTEM_INSTRUCTION,
    build_full_doc_answer_messages,
    build_router_messages,
    build_section_answer_messages,
    format_chunks,
    format_full_documents,
)
from doccontext.models.chunk import RetrievedChunk


def _chunk(**overrides) -> RetrievedChunk:
    base = dict(
        chunk_id="ck-1",
        document_id="doc-1",
        corpus_id="corp-1",
        client_id="tenant-1",
        chunk_index=0,
        char_start=0,
        char_end=5,
        text="hello",
        file_type="txt",
        score=0.9,
    )
    base.update(overrides)
    return RetrievedChunk(**base)


def test_router_messages_put_user_prompt_first() -> None:
    msgs = build_router_messages("what is this doc about?")
    assert msgs[0] == Message(role="user", content="what is this doc about?")
    assert msgs[-1].role == "system"
    assert msgs[-1].content == ROUTER_SYSTEM_INSTRUCTION


def test_section_answer_messages_order_and_content() -> None:
    history = [
        Message(role="user", content="previous Q"),
        Message(role="assistant", content="previous A"),
    ]
    chunks = [_chunk(chunk_id="ck-a", text="alpha"), _chunk(chunk_id="ck-b", text="beta")]
    msgs = build_section_answer_messages(
        user_prompt="follow up?", history=history, chunks=chunks
    )

    # user first, history next, then system instruction, then chunks.
    assert msgs[0] == Message(role="user", content="follow up?")
    assert msgs[1:3] == history
    assert msgs[3].role == "system"
    assert msgs[3].content == ANSWER_SECTION_SYSTEM_INSTRUCTION
    assert msgs[4].role == "system"
    assert "ck-a" in msgs[4].content and "ck-b" in msgs[4].content
    assert "alpha" in msgs[4].content and "beta" in msgs[4].content


def test_full_doc_answer_messages_order_and_content() -> None:
    docs = [("doc-1", "full body of doc 1"), ("doc-2", "body of doc 2")]
    msgs = build_full_doc_answer_messages(
        user_prompt="summarise both",
        history=[],
        documents=docs,
    )
    assert msgs[0] == Message(role="user", content="summarise both")
    assert msgs[1].content == ANSWER_FULL_DOC_SYSTEM_INSTRUCTION
    assert "document_id=doc-1" in msgs[2].content
    assert "document_id=doc-2" in msgs[2].content
    assert "full body of doc 1" in msgs[2].content


def test_format_chunks_is_deterministic() -> None:
    chunks = [_chunk(chunk_id="ck-1", text="A"), _chunk(chunk_id="ck-2", text="B")]
    rendered = format_chunks(chunks)
    assert rendered.index("chunk_id=ck-1") < rendered.index("chunk_id=ck-2")
    # Two runs produce identical output.
    assert rendered == format_chunks(chunks)


def test_format_full_documents_preserves_order() -> None:
    rendered = format_full_documents([("x", "alpha"), ("y", "beta")])
    assert rendered.index("document_id=x") < rendered.index("document_id=y")


def test_empty_history_is_allowed_and_omitted() -> None:
    msgs = build_section_answer_messages(
        user_prompt="q", history=[], chunks=[_chunk()]
    )
    # user + 2 system messages, no history entries slotted in.
    assert [m.role for m in msgs] == ["user", "system", "system"]
