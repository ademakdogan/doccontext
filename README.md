# doccontext

A multi-tenant **Retrieval-Augmented Generation (RAG)** service. It indexes
`PDF` / `TXT` / `MD` documents into a vector store and answers natural-language
prompts over them through a **two-stage LLM flow** (route → answer), exposed over
**gRPC**.

The system is split into two long-running processes:

- a **gRPC server** that accepts requests and answers queries synchronously, and
- a **worker** that does the heavy lifting (extract → chunk → embed → upsert,
  and deletes) asynchronously off a RabbitMQ queue.

Every storage backend is pluggable behind a small interface + factory:
embedders, vector stores, and the queue can each be swapped via configuration.

---

## Table of contents

- [Architecture](#architecture)
- [How it works](#how-it-works)
  - [Indexing pipeline](#indexing-pipeline)
  - [Query flow (two-stage LLM)](#query-flow-two-stage-llm)
  - [Multi-tenancy](#multi-tenancy)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [gRPC API reference](#grpc-api-reference)
  - [IndexDocument](#indexdocument)
  - [GetIndexingJobStatus](#getindexingjobstatus)
  - [QueryDocuments](#querydocuments)
  - [DeleteDocument](#deletedocument)
  - [Common enums](#common-enums)
- [Using the service](#using-the-service)
- [Development](#development)
- [Project layout](#project-layout)

---

## Architecture

```
                                +-------------------+
   gRPC client ───────────────► |   gRPC server     |
                                |  (doccontext.server)
                                +---------+---------+
                                          |
        IndexDocument / DeleteDocument    |    QueryDocuments
        (write job row, publish msg)      |    (synchronous, two-stage LLM)
                                          |
              +-------------+    +--------v--------+    +-----------------+
              | PostgreSQL  |◄───┤  Job repository │    |    OpenRouter    │
              | indexing_   |    +-----------------+    |  (router + answer)
              | jobs table  |             |             +--------+--------+
              +------+------+             |                      |
                     ▲          publish   ▼  consume             │ embed query
          status     │        +-----------------+                │ + search/scroll
          updates    │        |    RabbitMQ      |                ▼
                     │        |  document_jobs   |        +---------------+
                     │        +--------+--------+         |    Qdrant     |
                     │                 |                  | (vector store)|
                     │                 ▼                  +-------+-------+
                     │        +-----------------+                 ▲
                     └────────┤  Worker          ├────────────────┘
                              | (doccontext.worker)  extract→chunk→embed→upsert
                              +-----------------+
```

**Components**

| Component       | Default backend                       | Role |
|-----------------|---------------------------------------|------|
| Vector store    | Qdrant                                | Stores chunk embeddings + payload; tenant/corpus-filtered search |
| Queue           | RabbitMQ                              | Decouples the API from indexing/deletion work |
| Job repository  | PostgreSQL (SQLAlchemy async)         | Tracks job lifecycle: `QUEUED → RUNNING → SUCCEEDED/FAILED` |
| Embedder        | `all-MiniLM-L6-v2` (384-dim, cosine)  | Turns text into vectors |
| LLM             | OpenRouter (`openai/gpt-5-mini`)      | Stage-1 routing + stage-2 answering |
| Chunker         | Recursive character chunker           | 800 chars / 160 overlap by default |
| Extractors      | `pypdf` / plain-text / markdown       | PDF, TXT, MD → text |

All of these are resolved through factories (`embeddings/factory.py`,
`vector_stores/factory.py`, `queue/factory.py`, `llm/factory.py`), selected by
the `*_PROVIDER` settings.

---

## How it works

### Indexing pipeline

1. A client calls **`IndexDocument`** with a `storage_path` pointing at a file
   the server/worker can read.
2. The server writes a `QUEUED` job row to Postgres and publishes a job
   envelope to the `document_jobs` RabbitMQ queue, then returns immediately with
   a `job_id`. The RPC is intentionally fire-and-forget.
3. The **worker** consumes the message, moves the job to `RUNNING`, then:
   - extracts text (`pypdf` for PDF, decode for TXT/MD),
   - chunks it (recursive, `CHUNK_SIZE` / `CHUNK_OVERLAP`),
   - embeds each chunk with MiniLM,
   - ensures the Qdrant collection exists (sized to the embedder dimension),
   - **upserts** the chunks.
4. On success the job is marked `SUCCEEDED`; any exception marks it `FAILED`
   with the error message and re-raises so the queue drops the poison message.

Chunk IDs are **deterministic** (`uuid5` of `document_id:chunk_index`), so
re-indexing the same document overwrites the same vector points instead of
piling up duplicates.

### Query flow (two-stage LLM)

`QueryDocuments` is synchronous and runs two LLM calls behind a global
`asyncio.Semaphore` (capped at `MAX_CONCURRENT_QUERIES`) so the upstream LLM is
never stampeded:

**Stage 1 — Router.** A cheap classification call labels the question as either:
- **`SECTION`** — a specific fact/passage living in a small part of a document, or
- **`FULL_DOC`** — needs whole-document reasoning (summarize, compare, outline).

The router returns strict JSON `{"route": ..., "confidence": <0..1>}`. It
defaults conservatively to `SECTION` when unsure.

**Stage 2 — Answer**, branching on the route:
- **`SECTION`**: embed the question → vector `search` the top-k chunks within
  the tenant/corpus → ask the LLM to answer using only those chunks. Citations
  point at the retrieved chunks (with similarity `score`).
- **`FULL_DOC`**: `scroll` all chunks for the requested corpora, reconstruct
  full document text (chunks sorted by index, overlap de-duplicated) → ask the
  LLM to answer over the whole documents. Citations are one span per document.

The response carries the `answer`, the `used_route`, `citations`, and the
router's `confidence`.

> Prompt-ordering note: the user's question is always the **first** message in
> both stages so provider prompt caches stay warm across repeat queries.

### Multi-tenancy

Every record is scoped by `client_id` (tenant) and `corpus_id` (a collection of
documents within a tenant). Qdrant uses one collection (`<prefix>_chunks`) with
**payload keyword filters** on `client_id` / `corpus_id` / `document_id` —
indexed for fast equality filtering — applied on every search, scroll, and
delete. A query only ever sees vectors belonging to the caller's tenant and the
corpora it explicitly requests.

---

## Requirements

- **Python ≥ 3.13**
- **[uv](https://docs.astral.sh/uv/)** for dependency + environment management
- **Docker** (for Qdrant, RabbitMQ, Postgres) — or your own instances
- An **OpenRouter API key** for live queries

---

## Quick start

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
#   then edit .env and set OPENROUTER_API_KEY=...

# 3. Start the infrastructure (Qdrant + RabbitMQ + Postgres)
docker compose up -d

# 4. (Re)generate gRPC stubs — only needed if you edit the .proto
./scripts/generate_proto.sh

# 5. Run the gRPC server (terminal 1)
uv run python -m doccontext.server

# 6. Run the worker (terminal 2)
uv run python -m doccontext.worker

# 7. Drive the full flow end-to-end with the demo client (terminal 3)
uv run python tests/client.py
```

The server listens on `GRPC_HOST:GRPC_PORT` (default `0.0.0.0:50051`). The
Postgres `indexing_jobs` table and the Qdrant collection are bootstrapped
automatically on first run.

---

## Configuration

All settings are read from environment variables (or a `.env` file) via
`pydantic-settings`. See [.env.example](.env.example) for the full list. Key
groups:

| Variable | Default | Description |
|----------|---------|-------------|
| `GRPC_HOST` / `GRPC_PORT` | `0.0.0.0` / `50051` | gRPC bind address |
| `QDRANT_HOST` / `QDRANT_PORT` | `localhost` / `6333` | Vector store |
| `QDRANT_COLLECTION_PREFIX` | `doccontext` | Collection becomes `<prefix>_chunks` |
| `RABBITMQ_HOST` / `RABBITMQ_PORT` | `localhost` / `5672` | Queue broker |
| `RABBITMQ_DOCUMENT_JOBS_QUEUE` | `document_jobs` | Job queue name |
| `POSTGRES_*` | `doccontext` | Job repository connection |
| `EMBEDDING_PROVIDER` | `minilm` | Embedder factory key |
| `VECTOR_STORE_PROVIDER` | `qdrant` | Vector store factory key |
| `QUEUE_PROVIDER` | `rabbitmq` | Queue factory key |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `160` | Chunking parameters |
| `OPENROUTER_API_KEY` | *(empty)* | **Required** for live queries |
| `LLM_ROUTER_MODEL` | `openai/gpt-5-mini` | Stage-1 routing model |
| `LLM_ANSWER_MODEL` | `openai/gpt-5-mini` | Stage-2 answer model |
| `QUERY_TOP_K_DEFAULT` | `5` | Default `top_k` for SECTION search |
| `MAX_CONCURRENT_QUERIES` | `10` | Global query concurrency cap |
| `LOG_LEVEL` / `LOG_DIR` | `INFO` / `./logs` | Logging; one log file per RPC channel |

---

## gRPC API reference

Service: **`doccontext.v1.DocContext`** — defined in
[proto/doccontext.proto](proto/doccontext.proto). All four RPCs are unary
(single request → single response).

```protobuf
service DocContext {
  rpc IndexDocument(IndexDocumentRequest) returns (IndexDocumentResponse);
  rpc GetIndexingJobStatus(GetIndexingJobStatusRequest) returns (GetIndexingJobStatusResponse);
  rpc QueryDocuments(QueryDocumentsRequest) returns (QueryDocumentsResponse);
  rpc DeleteDocument(DeleteDocumentRequest) returns (DeleteDocumentResponse);
}
```

### IndexDocument

Queues a document for indexing. **Asynchronous**: returns a `job_id` with status
`QUEUED`; poll [`GetIndexingJobStatus`](#getindexingjobstatus) for completion.

**Request — `IndexDocumentRequest`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | no | Stable document identifier; auto-generated (uuid4) if omitted. Supply your own to make later deletes/re-indexes deterministic. |
| `client_id` | string | **yes** | Tenant identifier. |
| `user_id` | string | no | Acting user (for logging/audit). |
| `corpus_id` | string | **yes** | Corpus this document belongs to. |
| `file_type` | `FileType` | **yes** | `PDF`, `TXT`, or `MD`. |
| `storage_path` | string | **yes** | Filesystem path the worker can read. |
| `metadata` | map<string,string> | no | Arbitrary metadata. |

**Response — `IndexDocumentResponse`**: `job_id`, `status` (`QUEUED`).

**Errors**: `INVALID_ARGUMENT` if `client_id`, `corpus_id`, or `storage_path` is
missing, or `file_type` is unspecified/unknown.

### GetIndexingJobStatus

Reads the current state of any job (indexing **or** deletion).

**Request — `GetIndexingJobStatusRequest`**: `job_id` (**required**).

**Response — `GetIndexingJobStatusResponse`**: `job_id`, `document_id`,
`status` (`QUEUED` / `RUNNING` / `SUCCEEDED` / `FAILED`), `error_message`
(populated only on `FAILED`).

**Errors**: `INVALID_ARGUMENT` if `job_id` missing; `NOT_FOUND` if no such job.

### QueryDocuments

Answers a prompt over one or more corpora using the
[two-stage LLM flow](#query-flow-two-stage-llm). **Synchronous** — the answer
comes back in the response.

**Request — `QueryDocumentsRequest`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `client_id` | string | **yes** | Tenant identifier. |
| `user_id` | string | no | Acting user. |
| `chat_session_id` | string | no | Session id (for logging/grouping). |
| `corpus_ids` | repeated string | **yes** | One or more corpora to search; must be non-empty. |
| `prompt` | string | **yes** | The user's question. |
| `history_window` | int32 | no | Number of trailing user/assistant **pairs** from `history` to include. `0` disables history. |
| `top_k` | int32 | no | Chunks to retrieve on the SECTION path; falls back to `QUERY_TOP_K_DEFAULT` when `≤ 0`. |
| `history` | repeated `HistoryMessage` | no | Prior turns (`role` = `"user"`/`"assistant"`, `content`). Only the last `history_window` pairs are used. |

**Response — `QueryDocumentsResponse`**

| Field | Type | Description |
|-------|------|-------------|
| `answer` | string | The grounded answer. |
| `used_route` | `QueryRoute` | `SECTION` or `FULL_DOC` — the route the router chose. |
| `citations` | repeated `Citation` | Sources backing the answer. |
| `confidence` | double | The router's confidence (0..1). |

**`Citation`**: `document_id`, `corpus_id`, `chunk_index`, `char_start`,
`char_end`, `score` (similarity for SECTION; `0.0` for FULL_DOC spans).

**Errors**: `INVALID_ARGUMENT` if `client_id` or `prompt` is missing, or
`corpus_ids` is empty.

### DeleteDocument

Queues removal of all vectors for a document. **Asynchronous**: returns a
`job_id` with status `QUEUED`; poll [`GetIndexingJobStatus`](#getindexingjobstatus).

**Request — `DeleteDocumentRequest`**: `document_id` (**required**),
`client_id` (**required**), `user_id` (optional). The worker deletes every chunk
matching `(client_id, document_id)`.

**Response — `DeleteDocumentResponse`**: `job_id`, `status` (`QUEUED`).

**Errors**: `INVALID_ARGUMENT` if `client_id` or `document_id` is missing.

### Common enums

| Enum | Values |
|------|--------|
| `FileType` | `FILE_TYPE_UNSPECIFIED`, `PDF`, `TXT`, `MD` |
| `JobType` | `JOB_TYPE_UNSPECIFIED`, `INDEX_DOCUMENT`, `DELETE_DOCUMENT` |
| `JobStatus` | `JOB_STATUS_UNSPECIFIED`, `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED` |
| `QueryRoute` | `QUERY_ROUTE_UNSPECIFIED`, `SECTION`, `FULL_DOC` |

---

## Using the service

The generated Python stubs live in `doccontext.proto_gen`. A minimal client:

```python
import asyncio
import grpc
from doccontext.proto_gen import doccontext_pb2 as pb
from doccontext.proto_gen import doccontext_pb2_grpc as pb_grpc


async def main() -> None:
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = pb_grpc.DocContextStub(channel)

        # 1. Index a document
        idx = await stub.IndexDocument(pb.IndexDocumentRequest(
            document_id="my-doc-1",
            client_id="tenant-a",
            corpus_id="handbook",
            file_type=pb.PDF,
            storage_path="/abs/path/to/file.pdf",
        ))
        print("job:", idx.job_id, pb.JobStatus.Name(idx.status))

        # 2. Poll until the worker finishes
        while True:
            st = await stub.GetIndexingJobStatus(
                pb.GetIndexingJobStatusRequest(job_id=idx.job_id)
            )
            if st.status in (pb.SUCCEEDED, pb.FAILED):
                print("final:", pb.JobStatus.Name(st.status), st.error_message)
                break
            await asyncio.sleep(2)

        # 3. Ask a question
        ans = await stub.QueryDocuments(pb.QueryDocumentsRequest(
            client_id="tenant-a",
            corpus_ids=["handbook"],
            prompt="What is the refund policy?",
            top_k=5,
        ))
        print("route:", pb.QueryRoute.Name(ans.used_route))
        print("answer:", ans.answer)

        # 4. Delete the document
        await stub.DeleteDocument(pb.DeleteDocumentRequest(
            document_id="my-doc-1", client_id="tenant-a",
        ))


asyncio.run(main())
```

For a complete, annotated walkthrough of all four RPCs (including multi-turn
history and a validation-error demo), see
[tests/client.py](tests/client.py) — run it against a live stack with
`uv run python tests/client.py`.

---

## Development

```bash
# Run unit tests (no external services required)
uv run pytest tests/unit

# Run integration tests (require Docker services / network; opt-in marker)
docker compose up -d
uv run pytest -m integration

# Run the whole suite
uv run pytest

# Regenerate gRPC stubs after editing proto/doccontext.proto
./scripts/generate_proto.sh
```

Integration tests are gated behind the `integration` pytest marker (see
[pyproject.toml](pyproject.toml)). Unit tests cover chunking, extractors,
embeddings, config, logging, prompts, and the OpenRouter client in isolation.

---

## Project layout

```
proto/doccontext.proto          # gRPC service + message definitions
scripts/generate_proto.sh       # regenerate Python stubs into proto_gen/
docker-compose.yml              # Qdrant + RabbitMQ + Postgres

src/doccontext/
  server.py                     # gRPC server entrypoint (python -m doccontext.server)
  worker.py                     # queue consumer entrypoint (python -m doccontext.worker)
  config.py                     # pydantic-settings Settings
  ids.py                        # id helpers (deterministic chunk ids)
  logging_config.py             # structlog setup, per-RPC log channels

  services/                     # gRPC handlers (one file per RPC)
    servicer.py                 #   thin composition layer
    index_service.py            #   IndexDocument
    status_service.py           #   GetIndexingJobStatus
    query_service.py            #   QueryDocuments (two-stage flow)
    delete_service.py           #   DeleteDocument
    converters.py               #   proto <-> domain enum conversions

  workers/document_worker.py    # index/delete job execution
  repositories/job.py           # Postgres job lifecycle (SQLAlchemy async)
  embeddings/                   # Embedder interface + MiniLM + factory
  vector_stores/                # VectorStore interface + Qdrant + factory
  queue/                        # Queue interface + RabbitMQ + factory
  llm/                          # LLMClient + OpenRouter + prompts + factory
  chunking/                     # Chunker interface + recursive chunker
  extractors/                   # PDF / TXT / MD text extraction
  models/                       # domain dataclasses (Job, Chunk, ...)
  proto_gen/                    # generated gRPC stubs

tests/
  unit/                         # isolated unit tests
  integration/                  # service/infra tests (require Docker/network)
  client.py                     # standalone end-to-end demo client
```
