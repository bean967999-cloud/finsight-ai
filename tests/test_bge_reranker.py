from pathlib import Path

import pytest

from finsight.infrastructure.embedding.bge_reranker import BGERerankerProvider


class FakeTokenizer:
    def encode(self, first: str, second: str | None = None, **kwargs: object) -> list[int]:
        assert kwargs == {"add_special_tokens": True, "truncation": False}
        return list(range(len(first) + len(second or "") + 2))


class FakeModel:
    tokenizer = FakeTokenizer()

    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[str, str]], dict[str, object]]] = []

    def compute_score(self, pairs: list[tuple[str, str]], **kwargs: object) -> list[float]:
        self.calls.append((pairs, kwargs))
        return [0.9 - index / 10 for index in range(len(pairs))]


def test_adapter_checks_tokens_and_returns_aligned_normalized_scores() -> None:
    model = FakeModel()
    provider = BGERerankerProvider(
        Path("unused"), model_version="fixture", model=model,
        batch_size=2, query_max_tokens=10, pair_max_tokens=20,
    )
    assert provider.score("利润", ("20亿元", "10亿元")) == (0.9, 0.8)
    assert model.calls[0][1] == {"batch_size": 2, "max_length": 20, "normalize": True}


def test_adapter_rejects_silent_truncation_and_missing_local_weights() -> None:
    model = FakeModel()
    provider = BGERerankerProvider(
        Path("unused"), model_version="fixture", model=model,
        query_max_tokens=4, pair_max_tokens=8,
    )
    with pytest.raises(ValueError, match="query exceeds"):
        provider.score("问题过长", ("正文",))
    with pytest.raises(ValueError, match="pair exceeds"):
        provider.score("问题", ("正文内容过长",))
    assert model.calls == []

    with pytest.raises(FileNotFoundError, match="does not exist"):
        BGERerankerProvider(Path("missing-reranker"), model_version="fixture")
