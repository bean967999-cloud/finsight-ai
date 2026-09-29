"""Deployment validation is offline; wiring tests do not load models or connect DB."""

from types import SimpleNamespace

import pytest

from finsight.core.deployment import require_runtime_environment, validate_runtime_environment
from finsight.workers.deployment import create_application, wire_research_services


def contract(tmp_path):
    embedding = tmp_path / "BgeM3"
    reranker = tmp_path / "Reranker"
    storage = tmp_path / "Documents"
    evaluation = tmp_path / "EvaluationRuns"
    for directory in (embedding, reranker, storage, evaluation):
        directory.mkdir()
    for directory in (embedding, reranker):
        (directory / "config.json").write_text("{}")
        (directory / "model.safetensors").write_bytes(b"test manifest only")
    return {
        "APP_ENV": "deploy", "APP_HOST": "0.0.0.0", "APP_PORT": "9300",
        "AUTH_JWT_SECRET": "test-only-" + "x" * 40, "AUTH_TOKEN_MINUTES": "30",
        "DATABASE_URL": "postgresql+psycopg://finsight:test-only-password@postgres:5432/finsight",
        "REDIS_URL": "redis://redis:6379/0", "MILVUS_URI": "http://milvus:19530",
        "MILVUS_COLLECTION": "test_v1", "MINERU_API_URL": "http://mineru:8000",
        "EMBEDDING_DIMENSION": "1024", "OBJECT_STORAGE_ROOT": str(storage),
        "EVALUATION_RUNS_ROOT": str(evaluation), "FINSIGHT_BGE_M3_PATH": str(embedding),
        "FINSIGHT_BGE_MODEL_PATH": str(embedding), "FINSIGHT_RERANKER_PATH": str(reranker),
        "FINSIGHT_RERANKER_VERSION": "test-v1", "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }


def test_explicit_valid_contract(tmp_path):
    assert validate_runtime_environment(contract(tmp_path)) == []


@pytest.mark.parametrize("key,value", [
    ("AUTH_JWT_SECRET", ""), ("APP_ENV", "dev"), ("APP_PORT", "bad"),
    ("AUTH_TOKEN_MINUTES", "121"),
    ("DATABASE_URL", "postgresql+psycopg://user:hidden-secret@localhost:55432/finsight"),
    ("MILVUS_URI", "http://milvus:bad"), ("FINSIGHT_BGE_MODEL_PATH", "/Other"),
    ("EVALUATION_RUNS_ROOT", "/"), ("HF_HUB_OFFLINE", "0"),
])
def test_runtime_refuses_invalid_contract_without_values(tmp_path, key, value):
    values = contract(tmp_path)
    values[key] = value
    with pytest.raises(RuntimeError) as error:
        require_runtime_environment(values)
    assert "hidden-secret" not in str(error.value)


def test_missing_weight_manifest_refuses(tmp_path):
    from pathlib import Path

    values = contract(tmp_path)
    (Path(values["FINSIGHT_BGE_M3_PATH"]) / "model.safetensors").unlink()
    assert any("weight manifest" in error for error in validate_runtime_environment(values))


def test_app_factory_refuses_before_loading_models(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(RuntimeError, match="Deployment preflight refused"):
        create_application()


def test_wiring_connects_search_grounded_graph_and_workspace_evaluation(tmp_path):
    values = contract(tmp_path)
    settings = SimpleNamespace(object_storage_root=values["OBJECT_STORAGE_ROOT"],
                               evaluation_runs_root=values["EVALUATION_RUNS_ROOT"])
    application = SimpleNamespace(state=SimpleNamespace(structured_query=object()))
    search = object()
    sessions = object()
    assert wire_research_services(application, settings, sessions, search) is application
    assert application.state.evidence_search is search
    assert application.state.document_answer.search is search
    assert application.state.document_answer.sessions is sessions
    assert str(application.state.real_document_evaluation.root) == settings.evaluation_runs_root
    assert application.state.real_document_evaluation.grounded is application.state.document_answer
    assert application.state.research_graph is not None
