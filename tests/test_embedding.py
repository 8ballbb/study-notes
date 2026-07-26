import pytest

from study_notes.embedding import Embedder, FakeEmbedder


def test_fake_embedder_dim_and_determinism():
    emb: Embedder = FakeEmbedder(dim=1024)
    a = emb.embed(["hello world"])
    b = emb.embed(["hello world"])
    assert len(a) == 1
    assert len(a[0]) == 1024
    assert a == b  # deterministic


def test_fake_embedder_differs_by_text():
    emb = FakeEmbedder(dim=1024)
    out = emb.embed(["alpha", "beta"])
    assert out[0] != out[1]


@pytest.mark.slow
def test_bge_m3_embedder_shape():
    from study_notes.embedding import BGEM3Embedder

    emb = BGEM3Embedder()
    out = emb.embed(["distributed consensus"])
    assert len(out) == 1
    assert len(out[0]) == 1024
