import json
from hashlib import sha256
from pathlib import Path

import pytest

from finsight.domain.embedding import EmbeddingInput, EmbeddingOutput, EmbeddingSpec, QueryEmbedding
from finsight.services.embedding_readiness import check_embedding_readiness


def test_embedding_contract_accepts_dense_and_sparse_together() -> None:
    spec = EmbeddingSpec(dimension=3, model_max_tokens=100, batch_max_tokens=40, query_max_tokens=20)
    item = EmbeddingInput(
        chunk_id=1, document_id=2, chunk_version=3,
        content_sha256=sha256("收入同比增长".encode()).hexdigest(), text="收入同比增长",
    )
    output = EmbeddingOutput(
        chunk_id=item.chunk_id, model_name=spec.model_name,
        token_count=8, dense=(0.1, 0.2, 0.3), sparse={16: 0.7, 23: 0.4},
    )
    output.validate(spec)
    QueryEmbedding(spec.model_name, 4, (0.3, 0.2, 0.1), {16: 0.5}).validate(spec)


@pytest.mark.parametrize(
    "bad_output",
    [
        EmbeddingOutput(1, "BAAI/bge-m3", 41, (0.1, 0.2, 0.3), {1: 0.2}),
        EmbeddingOutput(1, "BAAI/bge-m3", 8, (0.1, 0.2), {1: 0.2}),
        EmbeddingOutput(1, "BAAI/bge-m3", 8, (0.1, float("nan"), 0.3), {1: 0.2}),
        EmbeddingOutput(1, "BAAI/bge-m3", 8, (0.1, 0.2, 0.3), {1: -0.2}),
        EmbeddingOutput(1, "other-model", 8, (0.1, 0.2, 0.3), {1: 0.2}),
    ],
)
def test_invalid_output_fails_before_indexing(bad_output: EmbeddingOutput) -> None:
    with pytest.raises(ValueError):
        bad_output.validate(EmbeddingSpec(dimension=3, model_max_tokens=100, batch_max_tokens=40, query_max_tokens=20))


def test_input_validation_and_token_limit() -> None:
    spec = EmbeddingSpec(model_max_tokens=8192, batch_max_tokens=4096)
    spec.validate_tokens(4096)
    with pytest.raises(ValueError):
        spec.validate_tokens(4097)
    with pytest.raises(ValueError):
        EmbeddingInput(1, 1, 1, "bad digest", "正文")
    with pytest.raises(ValueError):
        EmbeddingInput(1, 1, 1, "a" * 64, " ")
    with pytest.raises(ValueError, match="does not match"):
        EmbeddingInput(1, 1, 1, "a" * 64, "正文")


def test_readiness_detects_missing_files_and_packages(tmp_path: Path) -> None:
    report = check_embedding_readiness(tmp_path, EmbeddingSpec())
    assert not report.ready
    assert not report.model_files_present
    assert "model snapshot is missing required files" in report.problems


def test_readiness_checks_local_config_without_loading_weights(tmp_path: Path) -> None:
    for name in ("tokenizer.json", "pytorch_model.bin", "sparse_linear.pt"):
        (tmp_path / name).write_bytes(b"placeholder")
    (tmp_path / "config.json").write_text(json.dumps({"hidden_size": 1024}), encoding="utf-8")
    (tmp_path / "tokenizer_config.json").write_text(
        json.dumps({"model_max_length": 8192}), encoding="utf-8"
    )
    report = check_embedding_readiness(tmp_path, EmbeddingSpec())
    assert report.model_files_present
    assert report.actual_dimension == 1024
    assert report.actual_max_tokens == 8192
    assert all(not problem.startswith("configured") for problem in report.problems)
