from hashlib import sha256
from pathlib import Path

import pytest

from finsight.domain.embedding import EmbeddingInput, EmbeddingSpec
from finsight.infrastructure.embedding.bge_m3 import BGEM3EmbeddingProvider


class FakeTokenizer:
    def encode(self, text: str, *, add_special_tokens: bool, truncation: bool) -> list[int]:
        assert add_special_tokens and not truncation
        return [0, *range(len(text)), 2]


class FakeModel:
    tokenizer = FakeTokenizer()

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def encode_corpus(self, texts: list[str], **kwargs: object) -> dict[str, object]:
        self.calls.append(("corpus", kwargs))
        return {
            "dense_vecs": [[0.1, 0.2, 0.3] for _ in texts],
            "lexical_weights": [{"12": 0.7} for _ in texts],
        }

    def encode_queries(self, texts: list[str], **kwargs: object) -> dict[str, object]:
        self.calls.append(("query", kwargs))
        return {"dense_vecs": [[0.3, 0.2, 0.1]], "lexical_weights": [{"31": 0.5}]}


def item(chunk_id: int, text: str) -> EmbeddingInput:
    return EmbeddingInput(chunk_id, 7, 1, sha256(text.encode()).hexdigest(), text)


def provider(model: FakeModel) -> BGEM3EmbeddingProvider:
    return BGEM3EmbeddingProvider(
        Path("unused"), spec=EmbeddingSpec(
            dimension=3, model_max_tokens=100, batch_max_tokens=20, query_max_tokens=10,
        ), model=model, batch_size=2,
    )


def test_document_batch_produces_aligned_dense_and_sparse() -> None:
    model = FakeModel()
    outputs = provider(model).encode_documents((item(1, "收入"), item(2, "利润")))
    assert [output.chunk_id for output in outputs] == [1, 2]
    assert outputs[0].token_count == 4
    assert outputs[0].dense == (0.1, 0.2, 0.3)
    assert outputs[0].sparse == {12: 0.7}
    assert model.calls[0][1] == {
        "batch_size": 2, "max_length": 20, "return_dense": True,
        "return_sparse": True, "return_colbert_vecs": False,
    }


def test_long_input_and_duplicate_ids_fail_before_model_call() -> None:
    model = FakeModel()
    adapter = provider(model)
    with pytest.raises(ValueError, match="exceeds"):
        adapter.encode_documents((item(1, "财" * 19),))
    with pytest.raises(ValueError, match="unique"):
        adapter.encode_documents((item(1, "收入"), item(1, "利润")))
    assert model.calls == []


def test_query_has_own_token_limit_and_no_fake_chunk_id() -> None:
    model = FakeModel()
    adapter = provider(model)
    query = adapter.encode_query("收入是多少")
    assert query.sparse == {31: 0.5}
    assert not hasattr(query, "chunk_id")
    with pytest.raises(ValueError, match="query exceeds"):
        adapter.encode_query("财" * 9)
    assert len(model.calls) == 1
