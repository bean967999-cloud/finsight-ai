"""HTTP acceptance scenarios using an isolated database and controlled handler."""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.api.routes.async_jobs import get_job_reader, get_submission_service
from finsight.domain.access_control import Role
from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document
from finsight.main import app
from finsight.services.async_job_dispatcher import AsyncJobDispatcher
from finsight.services.async_job_queue import QueueMessage
from finsight.services.async_job_reader import AsyncJobReader
from finsight.services.async_job_submission import AsyncJobSubmissionService
from finsight.services.async_job_worker import AsyncJobWorker
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.knowledge_scope import KnowledgeScopeService

SECRET = "test-only-signing-secret-at-least-32-bytes"
PASSWORD = "correct horse battery staple"


class MemoryQueue:
    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []
        self.acked: list[str] = []

    def publish(self, job_id: int, request_sha256: str) -> str:
        message_id = f"{len(self.messages) + len(self.acked) + 1}-0"
        self.messages.append(QueueMessage(message_id, job_id, request_sha256))
        return message_id

    def read_new(self, consumer: str, *, block_ms: int = 1000) -> QueueMessage | None:
        return self.messages.pop(0) if self.messages else None

    def reclaim_stale(self, consumer: str, *, min_idle_ms: int) -> QueueMessage | None:
        return None

    def acknowledge(self, message_id: str) -> None:
        self.acked.append(message_id)


class ControlledHandler:
    def __init__(self) -> None:
        self.fail = False

    def execute(self, task) -> str:
        if self.fail:
            raise OSError("source temporarily unavailable")
        return "document_parse_job:99"


@pytest.fixture
def scenario():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        document = Document(
            title="2024 annual report",
            document_type=DocumentType.ANNUAL_REPORT,
            company_code="TEST",
            report_year=2024,
            report_period_end=date(2024, 12, 31),
            object_key="documents/report.pdf",
            content_sha256="a" * 64,
            file_size_bytes=20,
        )
        session.add(document)
        session.flush()
        document_id = document.id
    identity = IdentityService(sessions)
    workspace_id = identity.create_workspace("Jobs Team")
    knowledge_base_id = identity.create_knowledge_base(workspace_id, "Reports")
    user_id = identity.provision("jobs-admin@example.com", PASSWORD)
    identity.assign_role(user_id, workspace_id, Role.WORKSPACE_ADMIN)
    identity.link_document(knowledge_base_id, document_id)
    previous_scope = app.state.knowledge_scope
    app.state.knowledge_scope = KnowledgeScopeService(sessions)
    app.state.auth_service = AuthenticationService(identity, TokenCodec(SECRET))
    headers = {"Authorization": f"Bearer {app.state.auth_service.login('jobs-admin@example.com', PASSWORD)}"}
    app.dependency_overrides[get_submission_service] = lambda: AsyncJobSubmissionService(sessions)
    app.dependency_overrides[get_job_reader] = lambda: AsyncJobReader(sessions)
    try:
        yield TestClient(app), sessions, document_id, knowledge_base_id, headers
    finally:
        app.dependency_overrides.clear()
        del app.state.auth_service
        app.state.knowledge_scope = previous_scope
        engine.dispose()


def _payload(document_id: int, knowledge_base_id, *, key: str = "report-2024", max_attempts: int = 3) -> dict:
    return {
        "idempotency_key": key,
        "knowledge_base_id": str(knowledge_base_id),
        "task": {"kind": "document_parse", "document_id": document_id},
        "max_attempts": max_attempts,
    }


def test_submit_poll_retry_and_success_scenario(scenario) -> None:
    client, sessions, document_id, base_id, headers = scenario
    created = client.post("/api/v1/jobs", headers=headers, json=_payload(document_id, base_id))
    assert created.status_code == 202
    job_id = created.json()["job"]["job_id"]
    assert created.headers["Location"] == f"/api/v1/jobs/{job_id}"
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["status"] == "pending"

    replay = client.post("/api/v1/jobs", headers=headers, json=_payload(document_id, base_id))
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["job"]["job_id"] == job_id

    queue = MemoryQueue()
    dispatcher = AsyncJobDispatcher(sessions, queue)
    handler = ControlledHandler()
    worker = AsyncJobWorker(sessions, queue, handler)
    assert dispatcher.dispatch_pending() == (job_id,)
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["status"] == "queued"
    handler.fail = True
    assert worker.process_one("test-worker").status == "retry_wait"
    waiting = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert waiting["attempt_count"] == 1
    assert waiting["error_code"] == "OSError"
    assert waiting["next_retry_at"] is not None
    due = waiting["next_retry_at"]
    retry_time = datetime.fromisoformat(due)
    assert dispatcher.dispatch_pending(now=retry_time - timedelta(seconds=1)) == ()
    assert dispatcher.dispatch_pending(now=retry_time) == (job_id,)
    handler.fail = False
    assert worker.process_one("test-worker").status == "succeeded"
    finished = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert finished["attempt_count"] == 2
    assert finished["result_ref"] == "document_parse_job:99"
    assert finished["error_code"] is None


def test_invalid_submission_conflict_and_missing_job(scenario) -> None:
    client, _, document_id, base_id, headers = scenario
    assert client.get("/api/v1/jobs/0", headers=headers).status_code == 422
    assert client.get("/api/v1/jobs/9999", headers=headers).status_code == 404
    assert client.post("/api/v1/jobs", headers=headers, json=_payload(9999, base_id)).status_code == 422
    assert client.post("/api/v1/jobs", headers=headers, json=_payload(document_id, base_id)).status_code == 202
    assert client.post(
        "/api/v1/jobs", headers=headers, json=_payload(document_id, base_id, max_attempts=4)
    ).status_code == 409


def test_status_api_exposes_terminal_failure_without_retry_time(scenario) -> None:
    client, sessions, document_id, base_id, headers = scenario
    created = client.post("/api/v1/jobs", headers=headers, json=_payload(document_id, base_id, max_attempts=1))
    job_id = created.json()["job"]["job_id"]
    queue = MemoryQueue()
    assert AsyncJobDispatcher(sessions, queue).dispatch_pending() == (job_id,)
    handler = ControlledHandler()
    handler.fail = True
    assert AsyncJobWorker(sessions, queue, handler).process_one("test-worker").status == "failed"
    finished = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert finished.status_code == 200
    assert finished.json()["attempt_count"] == 1
    assert finished.json()["error_code"] == "OSError"
    assert finished.json()["next_retry_at"] is None
    assert AsyncJobDispatcher(sessions, queue).dispatch_pending() == ()


def test_job_scope_rejects_missing_identity_and_unlinked_document(scenario) -> None:
    client, sessions, document_id, base_id, headers = scenario
    payload = _payload(document_id, base_id)
    assert client.post("/api/v1/jobs", json=payload).status_code == 401
    assert client.post("/api/v1/jobs", headers=headers, json={
        **payload, "knowledge_base_id": None,
    }).status_code == 422
    other_base = IdentityService(sessions).create_knowledge_base(
        IdentityService(sessions).create_workspace("Other Jobs"), "Other Reports"
    )
    assert client.post("/api/v1/jobs", headers=headers, json={
        **payload, "knowledge_base_id": str(other_base),
    }).status_code == 403
    same_workspace = KnowledgeScopeService(sessions).workspace_for(base_id)
    assert same_workspace is not None
    unlinked_base = IdentityService(sessions).create_knowledge_base(same_workspace, "Unlinked Reports")
    assert client.post("/api/v1/jobs", headers=headers, json={
        **payload, "knowledge_base_id": str(unlinked_base),
    }).status_code == 422


def test_document_upload_validation_replay_and_conflict(scenario, monkeypatch, tmp_path):
    import base64

    from finsight.api.routes import async_jobs

    client, sessions, _, base_id, headers = scenario
    monkeypatch.setattr(async_jobs, "SessionFactory", sessions)
    from finsight.core.config import get_settings

    monkeypatch.setattr(get_settings(), "object_storage_root", str(tmp_path))
    payload = {"knowledge_base_id": str(base_id), "idempotency_key": "upload-probe",
               "title": "Disclosure", "company_code": "SAMPLE", "report_year": 2024,
               "pdf_base64": base64.b64encode(b"%PDF-1.7\nfixture only\n%%EOF").decode()}
    assert client.post("/api/v1/jobs/documents/upload", json=payload).status_code == 401
    assert client.post("/api/v1/jobs/documents/upload", headers=headers,
                       json={**payload, "pdf_base64": "not-a-pdf"}).status_code == 422
    first = client.post("/api/v1/jobs/documents/upload", headers=headers, json=payload)
    assert first.status_code == 201
    second = client.post("/api/v1/jobs/documents/upload", headers=headers, json=payload)
    assert second.status_code == 201 and second.json() == first.json()
    assert client.post("/api/v1/jobs/documents/upload", headers=headers,
                       json={**payload, "title": "Different"}).status_code == 409
    other = IdentityService(sessions).create_knowledge_base(
        KnowledgeScopeService(sessions).workspace_for(base_id), "No implicit file grants")
    assert client.post("/api/v1/jobs/documents/upload", headers=headers,
                       json={**payload, "knowledge_base_id": str(other)}).status_code == 409
    listed = client.get(f"/api/v1/jobs/documents?knowledge_base_id={base_id}", headers=headers)
    assert listed.status_code == 200
    assert any(d["document_id"] == first.json()["document_id"] for d in listed.json()["documents"])
    assert client.post("/api/v1/jobs/documents/chunks", headers=headers, json={
        "knowledge_base_id": str(base_id), "parse_job_id": 99999}).status_code == 422
