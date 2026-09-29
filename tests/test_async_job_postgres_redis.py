"""Opt-in end-to-end dispatch/claim using isolated PostgreSQL and Redis names."""

import os
from datetime import date
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.async_job import AsyncJobSubmission, DocumentParseTask
from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import AsyncJob, Document
from finsight.infrastructure.queue.redis_stream import RedisStreamQueue
from finsight.services.async_job_dispatcher import AsyncJobDispatcher
from finsight.services.async_job_submission import AsyncJobSubmissionService
from finsight.services.async_job_worker import AsyncJobWorker

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1"
    or os.environ.get("FINSIGHT_REDIS_INTEGRATION") != "1",
    reason="Enable both project PostgreSQL and Redis integration flags",
)


class RecordingHandler:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, task) -> str:
        self.calls += 1
        return "document_parse_job:99"


def test_durable_submission_dispatch_and_worker_ack() -> None:
    schema = f"finsight_queue_{uuid4().hex[:12]}"
    stream = f"finsight:test:async_jobs:{uuid4().hex}"
    group = f"finsight:test:workers:{uuid4().hex}"
    admin = create_engine(get_settings().database_url)
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    test_engine = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        test_engine = create_engine(
            get_settings().database_url,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        with sessions() as session, session.begin():
            document = Document(
                title="2024 report",
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
        request = AsyncJobSubmission(
            idempotency_key="parse-one",
            task=DocumentParseTask(document_id=document_id),
        )
        submitted = AsyncJobSubmissionService(sessions).submit(request)
        queue = RedisStreamQueue(client, stream=stream, group=group)
        queue.ensure_group()
        assert AsyncJobDispatcher(sessions, queue).dispatch_pending() == (submitted.job.job_id,)
        handler = RecordingHandler()
        outcome = AsyncJobWorker(sessions, queue, handler).process_one(
            "integration-worker",
            block_ms=100,
        )
        assert outcome is not None and outcome.status == "succeeded"
        assert handler.calls == 1
        assert client.xpending(stream, group)["pending"] == 0
        with sessions() as session:
            stored = session.get(AsyncJob, submitted.job.job_id)
            assert stored is not None and stored.result_ref == "document_parse_job:99"
            assert stored.attempt_count == 1
    finally:
        client.delete(stream)
        client.close()
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
