"""Two-stage QueryDocuments RPC handler.

Stage 1 — router: classify the user's question as FULL_DOC or SECTION.
Stage 2 — answer: either retrieve top-k chunks (SECTION) or reconstruct
whole documents from stored chunks (FULL_DOC), then ask the LLM for a
grounded reply.

Concurrency is capped globally via an ``asyncio.Semaphore`` so we never
stampede the upstream LLM.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import grpc

from doccontext.config import Settings, get_settings
from doccontext.embeddings.base import Embedder
from doccontext.llm.base import LLMClient, Message
from doccontext.llm.prompts import (
    build_full_doc_answer_messages,
    build_router_messages,
    build_section_answer_messages,
)
from doccontext.logging_config import LogChannel, get_logger
from doccontext.models.chunk import RetrievedChunk
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.services.converters import query_route_to_proto
from doccontext.vector_stores.base import VectorStore


@dataclass(frozen=True, slots=True)
class RouterDecision:
    route: str  # "SECTION" | "FULL_DOC"
    confidence: float


@dataclass(frozen=True, slots=True)
class AnswerPayload:
    answer: str
    citations: list[dict[str, Any]]


class QueryDocumentsHandler:
    def __init__(
        self,
        *,
        embedder: Embedder,
        vector_store: VectorStore,
        llm: LLMClient,
        settings: Settings | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._embedder = embedder
        self._store = vector_store
        self._llm = llm
        self._settings = settings or get_settings()
        self._sem = semaphore or asyncio.Semaphore(
            self._settings.max_concurrent_queries
        )
        self._log = get_logger(LogChannel.QUERY_DOCUMENTS)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._sem

    async def handle(
        self,
        request: pb.QueryDocumentsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.QueryDocumentsResponse:
        if not request.client_id:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "client_id is required"
            )
        if not request.prompt:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "prompt is required")
        if not list(request.corpus_ids):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "corpus_ids must not be empty"
            )

        corpus_ids = list(request.corpus_ids)
        top_k = request.top_k if request.top_k > 0 else self._settings.query_top_k_default
        history_window = max(0, int(request.history_window))
        history_pairs = _trim_history(list(request.history), history_window)

        log = self._log.bind(
            client_id=request.client_id,
            user_id=request.user_id,
            chat_session_id=request.chat_session_id,
            corpus_ids=corpus_ids,
            top_k=top_k,
            history_window=history_window,
            model_router=self._settings.llm_router_model,
            model_answer=self._settings.llm_answer_model,
        )

        start = time.monotonic()
        async with self._sem:
            router_resp = await self._llm.complete(
                build_router_messages(request.prompt),
                model=self._settings.llm_router_model,
                response_format={"type": "json_object"},
            )
            decision = _parse_router_decision(router_resp.content)

            citations_proto: list[pb.Citation] = []
            if decision.route == "FULL_DOC":
                docs = await asyncio.to_thread(
                    self._store.list_chunks_for_corpora,
                    client_id=request.client_id,
                    corpus_ids=corpus_ids,
                )
                assembled = _assemble_documents(docs)
                answer_resp = await self._llm.complete(
                    build_full_doc_answer_messages(
                        user_prompt=request.prompt,
                        history=history_pairs,
                        documents=assembled,
                    ),
                    model=self._settings.llm_answer_model,
                    response_format={"type": "json_object"},
                )
                citations_proto = _citations_for_full_doc(docs)
            else:
                query_vec = await asyncio.to_thread(
                    self._embedder.embed_one, request.prompt
                )
                hits = await asyncio.to_thread(
                    self._store.search,
                    query_vector=query_vec,
                    client_id=request.client_id,
                    corpus_ids=corpus_ids,
                    top_k=top_k,
                )
                answer_resp = await self._llm.complete(
                    build_section_answer_messages(
                        user_prompt=request.prompt,
                        history=history_pairs,
                        chunks=hits,
                    ),
                    model=self._settings.llm_answer_model,
                    response_format={"type": "json_object"},
                )
                citations_proto = _citations_for_section(hits)

        payload = _parse_answer_payload(answer_resp.content)
        total_tokens = (
            router_resp.usage.total_tokens + answer_resp.usage.total_tokens
        )
        input_tokens = (
            router_resp.usage.prompt_tokens + answer_resp.usage.prompt_tokens
        )
        output_tokens = (
            router_resp.usage.completion_tokens + answer_resp.usage.completion_tokens
        )

        log.info(
            "query_documents answered",
            route=decision.route,
            confidence=decision.confidence,
            duration_ms=int((time.monotonic() - start) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

        return pb.QueryDocumentsResponse(
            answer=payload.answer,
            used_route=query_route_to_proto(decision.route),
            citations=citations_proto,
            confidence=decision.confidence,
        )


def _trim_history(
    history: Sequence[pb.HistoryMessage], window: int
) -> list[Message]:
    """Keep only the last ``window`` user/assistant PAIRS (2 messages each).

    Everything outside the window is discarded. Order of retained messages
    is preserved as supplied.
    """
    if window <= 0 or not history:
        return []
    # A pair is one user turn + one assistant turn. We count backwards through
    # the supplied history and keep up to ``window`` pairs; partial tails
    # (a dangling user turn) are kept so the model can see the immediate
    # context.
    keep = window * 2
    tail = list(history)[-keep:]
    return [Message(role=_role_of(m.role), content=m.content) for m in tail]


def _role_of(role: str) -> Any:
    return "assistant" if role.lower() == "assistant" else "user"


def _parse_router_decision(raw: str) -> RouterDecision:
    try:
        obj = json.loads(raw)
    except ValueError:
        return RouterDecision(route="SECTION", confidence=0.0)
    route = str(obj.get("route", "SECTION")).upper()
    if route not in ("SECTION", "FULL_DOC"):
        route = "SECTION"
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    # Clamp defensively; model may return out-of-range scores.
    conf = max(0.0, min(1.0, conf))
    return RouterDecision(route=route, confidence=conf)


def _parse_answer_payload(raw: str) -> AnswerPayload:
    try:
        obj = json.loads(raw)
    except ValueError:
        return AnswerPayload(answer=raw, citations=[])
    answer = str(obj.get("answer", ""))
    citations = obj.get("citations") or []
    if not isinstance(citations, list):
        citations = []
    return AnswerPayload(answer=answer, citations=citations)


def _assemble_documents(chunks: Sequence[RetrievedChunk]) -> list[tuple[str, str]]:
    """Reconstruct document text by concatenating chunks ordered by chunk_index.

    Adjacent chunks overlap (by design), so we dedupe on character ranges:
    if the next chunk's ``char_start`` lies inside the accumulated range, we
    only append the non-overlapping tail.
    """
    by_doc: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for c in chunks:
        by_doc[c.document_id].append(c)
    out: list[tuple[str, str]] = []
    for document_id, doc_chunks in by_doc.items():
        doc_chunks.sort(key=lambda c: c.chunk_index)
        pieces: list[str] = []
        cursor = 0
        for c in doc_chunks:
            if c.char_start >= cursor:
                pieces.append(c.text)
            else:
                overlap = cursor - c.char_start
                pieces.append(c.text[overlap:])
            cursor = max(cursor, c.char_end)
        out.append((document_id, "".join(pieces)))
    return out


def _citations_for_section(hits: Sequence[RetrievedChunk]) -> list[pb.Citation]:
    return [
        pb.Citation(
            document_id=c.document_id,
            corpus_id=c.corpus_id,
            chunk_index=c.chunk_index,
            char_start=c.char_start,
            char_end=c.char_end,
            score=c.score,
        )
        for c in hits
    ]


def _citations_for_full_doc(
    chunks: Sequence[RetrievedChunk],
) -> list[pb.Citation]:
    """One citation per distinct document touched, covering its full span."""
    spans: dict[str, dict[str, Any]] = {}
    for c in chunks:
        s = spans.get(c.document_id)
        if s is None:
            spans[c.document_id] = {
                "corpus_id": c.corpus_id,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
            }
        else:
            s["char_start"] = min(s["char_start"], c.char_start)
            s["char_end"] = max(s["char_end"], c.char_end)
            s["chunk_index"] = min(s["chunk_index"], c.chunk_index)
    return [
        pb.Citation(
            document_id=doc_id,
            corpus_id=s["corpus_id"],
            chunk_index=s["chunk_index"],
            char_start=s["char_start"],
            char_end=s["char_end"],
            score=0.0,
        )
        for doc_id, s in spans.items()
    ]
