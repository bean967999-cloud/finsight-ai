from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finsight.api.routes.health import router
from finsight.services.deployment_health import DeploymentReadiness


def client():
    app = FastAPI()
    app.include_router(router)
    return app, TestClient(app)


def test_liveness_does_not_pretend_readiness():
    app, http = client()
    assert http.get("/health/live").status_code == 200
    assert http.get("/health/startup").status_code == 503
    assert http.get("/health/ready").status_code == 503
    app.state.startup_complete = True
    assert http.get("/health/startup").status_code == 200
    assert http.get("/health/ready").status_code == 503


def test_readiness_requires_all_checks_and_hides_exception(monkeypatch):
    app, http = client()
    checker = DeploymentReadiness(app, SimpleNamespace(), None)

    def failure():
        raise RuntimeError("password=must-not-display")

    monkeypatch.setattr(checker, "checks", lambda: {"database_schema": failure, "redis": lambda: True})
    app.state.deployment_readiness = checker
    app.state.startup_complete = True
    response = http.get("/health/ready")
    assert response.status_code == 503
    assert "must-not-display" not in response.text
    assert response.json()["checks"]["redis"] == "ok"
    monkeypatch.setattr(checker, "checks", lambda: {"database_schema": lambda: True})
    assert http.get("/health/ready").status_code == 200


def test_false_check_is_not_ready(monkeypatch):
    checker = DeploymentReadiness(None, None, None)
    monkeypatch.setattr(checker, "checks", lambda: {"storage_access": lambda: False})
    assert checker.report()["status"] == "not_ready"


def test_vector_probe_reuses_client_without_closing_shared_connection(monkeypatch):
    import pymilvus

    clients = []

    class SharedClient:
        def __init__(self, **kwargs):
            clients.append(self)

        def describe_collection(self, name, timeout):
            names = ("vector_id", "document_id", "chunk_id", "chunk_version", "page_start",
                     "page_end", "model_name", "dense_vector", "sparse_vector")
            return {"fields": [{"name": n, "params": {"dim": 1024}} for n in names]}

        def close(self):
            raise AssertionError("Health probe must not disconnect shared search connection")

    monkeypatch.setattr(pymilvus, "MilvusClient", SharedClient)
    checker = DeploymentReadiness(None, SimpleNamespace(
        milvus_uri="http://milvus:19530", milvus_collection="Test", embedding_dimension=1024), None)
    assert checker.checks()["vector_schema"]()
    assert checker.checks()["vector_schema"]()
    assert len(clients) == 1
