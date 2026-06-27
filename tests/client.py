"""Standalone end-to-end gRPC client for the doccontext RAG service.

Unlike the pytest integration tests (which wire up fake doubles), this script
talks to a *live*, fully-wired server: real Qdrant, RabbitMQ, Postgres and
OpenRouter. It exercises every RPC of the ``DocContext`` service one-by-one and
prints a human-readable transcript so you can see exactly how the system
behaves end-to-end.

Flow:

    1. IndexDocument           -- queue the sample PDF for indexing
    2. GetIndexingJobStatus    -- poll until the worker finishes (SUCCEEDED)
    3. QueryDocuments          -- ask PDF-derived questions (SECTION + FULL_DOC),
                                  including a multi-turn (history) follow-up
    4. DeleteDocument          -- remove the document, poll the delete job,
                                  then re-query to prove the vectors are gone
    5. Validation demo         -- show INVALID_ARGUMENT on a bad request

Prerequisites (must be running before you start this script):
    - Postgres, Qdrant, RabbitMQ  (e.g. `docker compose up -d postgres qdrant`)
    - gRPC server:  `uv run python -m doccontext.server`
    - worker:       `uv run python -m doccontext.worker`

Run:
    uv run python tests/client.py
    uv run python tests/client.py --host localhost --port 50051 --pdf tests/data/cdc_21130_DS1.pdf
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import grpc

from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc

# --- tenant / corpus identifiers used throughout the run ---------------------
CLIENT_ID = "tenant-demo"
USER_ID = "user-demo"
CORPUS_ID = "nanotox"
DOCUMENT_ID = "cdc-21130-ds1"  # explicit so we can delete it later
CHAT_SESSION_ID = "session-demo"

DEFAULT_PDF = Path(__file__).parent / "data" / "cdc_21130_DS1.pdf"

# --- questions derived from the indexed PDF ---------------------------------
# "Mechanisms of Nanoparticle-Induced Oxidative Stress and Toxicity"
# SECTION = a specific fact living in a small part of the document.
# FULL_DOC = needs whole-document reasoning (summary / comparison / structure).
SECTION_QUESTIONS = [
    "What reactive oxygen species make up the pool of oxidative species "
    "described in the paper?",
    "Which enzyme catalyzes the one-electron reduction of molecular oxygen "
    "to form the superoxide anion?",
    "What is 8-OHdG a biomarker of?",
    "Which transition metals are involved in ROS generation via Fenton-type "
    "and Haber-Weiss reactions?",
]

FULL_DOC_QUESTIONS = [
    "Summarize the overall mechanisms of nanoparticle-induced oxidative stress "
    "described in this review.",
    "What are the key cellular signaling pathways affected by metal "
    "nanoparticles, and how do they relate to toxicity?",
    "Compare how oxidative stress arises in metal-based nanoparticles versus "
    "carbon nanotubes.",
]

# Terminal job states (no further transitions expected).
_TERMINAL = {pb.SUCCEEDED, pb.FAILED}


# --- pretty printing helpers -------------------------------------------------


def banner(title: str) -> None:
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}")


def step(title: str) -> None:
    print(f"\n--- {title} ---")


def print_citations(citations) -> None:
    if not citations:
        print("    citations: (none)")
        return
    print(f"    citations ({len(citations)}):")
    for c in citations:
        print(
            f"      - doc={c.document_id} corpus={c.corpus_id} "
            f"chunk_index={c.chunk_index} "
            f"chars={c.char_start}..{c.char_end} score={c.score:.4f}"
        )


# --- RPC wrappers ------------------------------------------------------------


async def index_document(stub: pb_grpc.DocContextStub, pdf_path: Path) -> str:
    step("RPC 1/4: IndexDocument")
    req = pb.IndexDocumentRequest(
        document_id=DOCUMENT_ID,
        client_id=CLIENT_ID,
        user_id=USER_ID,
        corpus_id=CORPUS_ID,
        file_type=pb.PDF,
        storage_path=str(pdf_path.resolve()),
        metadata={"title": "Mechanisms of NP-Induced Oxidative Stress", "year": "2013"},
    )
    print(f"  storage_path = {req.storage_path}")
    print(f"  file_type    = {pb.FileType.Name(req.file_type)}")
    print(f"  corpus_id    = {req.corpus_id}")
    resp = await stub.IndexDocument(req)
    print(f"  -> job_id = {resp.job_id}")
    print(f"  -> status = {pb.JobStatus.Name(resp.status)}")
    return resp.job_id


async def poll_job(
    stub: pb_grpc.DocContextStub,
    job_id: str,
    *,
    label: str,
    timeout_s: float = 180.0,
    interval_s: float = 2.0,
) -> int:
    step(f"RPC 2/4: GetIndexingJobStatus (polling {label} job)")
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_status: int | None = None
    while True:
        resp = await stub.GetIndexingJobStatus(
            pb.GetIndexingJobStatusRequest(job_id=job_id)
        )
        if resp.status != last_status:
            print(f"  status -> {pb.JobStatus.Name(resp.status)}")
            last_status = resp.status
        if resp.status in _TERMINAL:
            if resp.status == pb.FAILED:
                print(f"  !! error_message: {resp.error_message}")
            return resp.status
        if asyncio.get_event_loop().time() > deadline:
            print(f"  !! timed out after {timeout_s:.0f}s "
                  f"(last status: {pb.JobStatus.Name(resp.status)})")
            return resp.status
        await asyncio.sleep(interval_s)


async def query(
    stub: pb_grpc.DocContextStub,
    prompt: str,
    *,
    expected_route: str | None = None,
    history: list[pb.HistoryMessage] | None = None,
    history_window: int = 0,
    top_k: int = 5,
) -> pb.QueryDocumentsResponse:
    print(f"\n  Q: {prompt}")
    if expected_route:
        print(f"     (expected route: {expected_route})")
    req = pb.QueryDocumentsRequest(
        client_id=CLIENT_ID,
        user_id=USER_ID,
        chat_session_id=CHAT_SESSION_ID,
        corpus_ids=[CORPUS_ID],
        prompt=prompt,
        top_k=top_k,
        history_window=history_window,
        history=history or [],
    )
    resp = await stub.QueryDocuments(req)
    print(f"     route      = {pb.QueryRoute.Name(resp.used_route)}")
    print(f"     confidence = {resp.confidence:.3f}")
    print(f"     A: {resp.answer}")
    print_citations(resp.citations)
    return resp


async def delete_document(stub: pb_grpc.DocContextStub) -> str:
    step("RPC 4/4: DeleteDocument")
    req = pb.DeleteDocumentRequest(
        document_id=DOCUMENT_ID,
        client_id=CLIENT_ID,
        user_id=USER_ID,
    )
    resp = await stub.DeleteDocument(req)
    print(f"  -> job_id = {resp.job_id}")
    print(f"  -> status = {pb.JobStatus.Name(resp.status)}")
    return resp.job_id


async def validation_demo(stub: pb_grpc.DocContextStub) -> None:
    step("Bonus: validation (expect INVALID_ARGUMENT)")
    try:
        await stub.QueryDocuments(
            pb.QueryDocumentsRequest(
                client_id=CLIENT_ID,
                corpus_ids=[CORPUS_ID],
                prompt="",  # missing required prompt
            )
        )
        print("  !! expected an error but the call succeeded")
    except grpc.aio.AioRpcError as exc:
        print(f"  -> code    = {exc.code().name}")
        print(f"  -> details = {exc.details()}")


# --- orchestration -----------------------------------------------------------


async def run(host: str, port: int, pdf_path: Path) -> int:
    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}", file=sys.stderr)
        return 2

    target = f"{host}:{port}"
    banner(f"doccontext end-to-end gRPC client  ->  {target}")
    print(f"  client_id={CLIENT_ID}  corpus_id={CORPUS_ID}  document_id={DOCUMENT_ID}")

    async with grpc.aio.insecure_channel(target) as channel:
        stub = pb_grpc.DocContextStub(channel)

        # 1 + 2: index, then wait for the worker to finish.
        index_job = await index_document(stub, pdf_path)
        status = await poll_job(stub, index_job, label="index")
        if status != pb.SUCCEEDED:
            print("\nIndexing did not succeed; aborting query phase.")
            return 1

        # 3: queries.
        banner("RPC 3/4: QueryDocuments")
        step("SECTION questions (specific facts)")
        for q in SECTION_QUESTIONS:
            await query(stub, q, expected_route="SECTION")

        step("FULL_DOC questions (whole-document reasoning)")
        last_full: pb.QueryDocumentsResponse | None = None
        last_prompt = ""
        for q in FULL_DOC_QUESTIONS:
            last_full = await query(stub, q, expected_route="FULL_DOC")
            last_prompt = q

        step("Multi-turn follow-up (uses history)")
        history = []
        if last_full is not None:
            history = [
                pb.HistoryMessage(role="user", content=last_prompt),
                pb.HistoryMessage(role="assistant", content=last_full.answer),
            ]
        await query(
            stub,
            "Which of those two is more associated with asbestos-like, "
            "fiber-shaped toxicity?",
            history=history,
            history_window=2,
        )

        # Bonus: validation behavior.
        await validation_demo(stub)

        # 4: delete + verify.
        delete_job = await delete_document(stub)
        del_status = await poll_job(stub, delete_job, label="delete")
        if del_status == pb.SUCCEEDED:
            step("Verify deletion (re-query the now-empty corpus)")
            await query(
                stub,
                "What reactive oxygen species make up the pool of oxidative "
                "species described in the paper?",
            )

    banner("Done.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="doccontext end-to-end gRPC client")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.host, args.port, args.pdf)))


if __name__ == "__main__":
    main()
