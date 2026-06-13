from __future__ import annotations

import math

import pytest

from doccontext.config import reload_settings
from doccontext.embeddings import (
    Embedder,
    UnknownEmbeddingProvider,
    clear_embedder_cache,
    get_embedder,
)


@pytest.fixture(scope="module")
def minilm() -> Embedder:
    return get_embedder()


def test_minilm_declares_contract(minilm: Embedder) -> None:
    assert minilm.name == "all-MiniLM-L6-v2"
    assert minilm.dim == 384


def test_minilm_embed_empty_input_returns_empty(minilm: Embedder) -> None:
    assert minilm.embed([]) == []


def test_minilm_embed_returns_one_vector_per_input_at_expected_dim(minilm: Embedder) -> None:
    out = minilm.embed(["alpha", "beta", "gamma"])
    assert len(out) == 3
    for v in out:
        assert len(v) == minilm.dim
        assert all(isinstance(x, float) for x in v)


def test_minilm_vectors_are_unit_normalized(minilm: Embedder) -> None:
    out = minilm.embed(["the quick brown fox jumps over the lazy dog"])
    norm = math.sqrt(sum(x * x for x in out[0]))
    assert math.isclose(norm, 1.0, abs_tol=1e-4)


def test_minilm_is_deterministic(minilm: Embedder) -> None:
    a = minilm.embed_one("repeatable input")
    b = minilm.embed_one("repeatable input")
    assert a == pytest.approx(b, rel=0, abs=1e-6)


def test_minilm_cosine_similarity_matches_meaning(minilm: Embedder) -> None:
    vs = minilm.embed([
        "how do I reset my password",
        "steps to change my login credentials",
        "pepperoni pizza recipe",
    ])
    def cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))
    assert cos(vs[0], vs[1]) > cos(vs[0], vs[2])


def test_factory_returns_cached_instance(isolated_env) -> None:
    isolated_env.setenv("EMBEDDING_PROVIDER", "minilm")
    reload_settings()
    clear_embedder_cache()
    a = get_embedder()
    b = get_embedder()
    assert a is b


def test_factory_rejects_unknown_provider(isolated_env) -> None:
    isolated_env.setenv("EMBEDDING_PROVIDER", "nope")
    reload_settings()
    clear_embedder_cache()
    with pytest.raises(UnknownEmbeddingProvider):
        get_embedder()


def test_factory_raises_not_implemented_for_reserved_providers(isolated_env) -> None:
    isolated_env.setenv("EMBEDDING_PROVIDER", "bge-m3")
    reload_settings()
    clear_embedder_cache()
    with pytest.raises(NotImplementedError):
        get_embedder()
