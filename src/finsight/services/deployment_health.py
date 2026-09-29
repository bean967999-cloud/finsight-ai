"""Bounded dependency checks returning statuses only, never connection details."""

import os
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit


class DeploymentReadiness:
    def __init__(self, application, settings, sessions):
        self.application, self.settings, self.sessions = application, settings, sessions
        self._vector_client = None
        self._vector_client_lock = Lock()

    def checks(self):
        import httpx
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from redis import Redis
        from sqlalchemy import text

        def database():
            with self.sessions() as session:
                session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
                session.execute(text("SELECT 1"))
                current = set(session.execute(text("SELECT version_num FROM alembic_version")).scalars())
                config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
                return current == set(ScriptDirectory.from_config(config).get_heads())

        def redis():
            with Redis.from_url(self.settings.redis_url, socket_timeout=2,
                                socket_connect_timeout=2) as client:
                return client.ping()

        def http_ok(url):
            with httpx.Client(timeout=2, trust_env=False) as client:
                return client.get(url).status_code == 200

        def milvus():
            uri = urlsplit(self.settings.milvus_uri)
            if uri.hostname != "milvus":
                return False
            return http_ok("http://milvus:9091/healthz")

        def vector_schema():
            from pymilvus import MilvusClient

            # Pymilvus shares connection aliases between clients for the same URI.
            # Closing a temporary probe would disconnect the live search adapter.
            # Keep a process-lifetime client; do not open/close one on each probe.
            with self._vector_client_lock:
                if self._vector_client is None:
                    self._vector_client = MilvusClient(uri=self.settings.milvus_uri, timeout=3)
                description = self._vector_client.describe_collection(
                    self.settings.milvus_collection, timeout=3
                )
            fields = {item["name"]: item for item in description["fields"]}
            required = {"vector_id", "document_id", "chunk_id", "chunk_version",
                        "page_start", "page_end", "model_name", "dense_vector", "sparse_vector"}
            return required <= fields.keys() and int(
                fields["dense_vector"].get("params", {}).get("dim", -1)
            ) == self.settings.embedding_dimension

        def storage():
            return all(Path(root).is_dir() and os.access(root, os.R_OK | os.W_OK | os.X_OK)
                       for root in (self.settings.object_storage_root,
                                    self.settings.evaluation_runs_root))

        def models():
            state = self.application.state
            return all(getattr(state, name, None) is not None for name in (
                "evidence_search", "document_answer", "real_document_evaluation", "auth_service",
            ))

        return {"database_schema": database, "redis": redis, "milvus": milvus,
                "vector_schema": vector_schema,
                "parser": lambda: http_ok(self.settings.mineru_api_url.rstrip("/") + "/health"),
                "storage_access": storage, "services_loaded": models}

    def report(self):
        statuses = {}
        for name, check in self.checks().items():
            try:
                statuses[name] = "ok" if check() else "unavailable"
            except Exception:  # noqa: BLE001 - health must not disclose exception payloads
                statuses[name] = "unavailable"
        return {"status": "ready" if all(v == "ok" for v in statuses.values()) else "not_ready",
                "checks": statuses}
