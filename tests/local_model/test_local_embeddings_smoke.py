"""Real local-model smoke. Run explicitly after `gridlens prepare-model`:

    .venv/bin/python -m pytest -m local_model -q

Default addopts still block IP sockets, so this proves inference runs offline.
"""

import math

import pytest

from gridlens.config import Settings
from gridlens.errors import AppError
from gridlens.providers.local_embeddings import LocalEmbeddingProvider, read_manifest

DOCUMENTS = [
    "A large load must apply to the grid operator before connection studies begin.",
    "The bakery sells sourdough bread every morning.",
]


@pytest.fixture(scope="module")
def provider():
    settings = Settings.from_env()
    try:
        read_manifest(settings)
    except AppError:
        pytest.skip("Local model is not prepared; a skip is not a successful model check")
    return LocalEmbeddingProvider(settings)


@pytest.mark.local_model
def test_real_model_embeds_offline_with_pinned_revision(provider):
    documents = provider.embed(DOCUMENTS, "document")
    query = provider.embed(["How does a data centre apply for a grid connection?"], "query")
    assert len(documents.revision) == 40 and documents.revision == query.revision
    assert documents.dimensions == query.dimensions == 384
    assert provider.manifest.max_seq_length == 512
    for vector in [*documents.vectors, *query.vectors]:
        assert len(vector) == 384
        assert abs(math.sqrt(sum(n * n for n in vector)) - 1) < 1e-3
    scores = [
        sum(a * b for a, b in zip(query.vectors[0], d, strict=True)) for d in documents.vectors
    ]
    assert scores[0] > scores[1]
    print(f"revision={documents.revision} dims={documents.dimensions} scores={scores}")


@pytest.mark.local_model
def test_real_model_is_reproducible_and_rejects_overlong_input(provider):
    first = provider.embed(DOCUMENTS, "document")
    second = provider.embed(DOCUMENTS, "document")
    assert all(
        abs(a - b) < 1e-6
        for v1, v2 in zip(first.vectors, second.vectors, strict=True)
        for a, b in zip(v1, v2, strict=True)
    )
    with pytest.raises(AppError) as raised:
        provider.embed(["grid " * 600], "document")
    assert raised.value.code == "EMBEDDING_INPUT_TOO_LONG"
