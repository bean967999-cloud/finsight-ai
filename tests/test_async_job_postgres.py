"""Opt-in PostgreSQL concurrency test in an isolated temporary schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.script import ScriptDirectory
from finsight.core.config import get_settings
from finsight.domain.async_job import AsyncJobSubmission, DocumentParseTask
from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import AsyncJob, Document
from finsight.services.async_job_submission import AsyncJobSubmissionService

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 for isolated PostgreSQL job concurrency",
)


def test_concurrent_same_key_creates_one_persistent_job() -> None:
    schema = f"finsight_async_{uuid4().hex[:12]}"
    admin = create_engine(get_settings().database_url)
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
                title="2024 annual report",
                document_type=DocumentType.ANNUAL_REPORT,
                company_code="TEST",
                report_year=2024,
                report_period_end=date(2024, 12, 31),
                object_key="documents/example.pdf",
                content_sha256="a" * 64,
                file_size_bytes=20,
            )
            session.add(document)
            session.flush()
            document_id = document.id
        request = AsyncJobSubmission(
            idempotency_key="same-submit",
            task=DocumentParseTask(document_id=document_id),
        )
        gate = Barrier(2)

        def submit_once():
            gate.wait(timeout=5)
            return AsyncJobSubmissionService(sessions).submit(request)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(submit_once)
            second = pool.submit(submit_once)
            outcomes = (first.result(timeout=10), second.result(timeout=10))
        assert outcomes[0].job.job_id == outcomes[1].job.job_id
        assert sorted(item.replayed for item in outcomes) == [False, True]
        with sessions() as session:
            assert len(list(session.scalars(select(AsyncJob)))) == 1
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_migration_creates_async_jobs_in_isolated_schema(monkeypatch) -> None:
    schema = f"finsight_migration_{uuid4().hex[:12]}"
    admin = create_engine(get_settings().database_url)
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        isolated_url = (
            make_url(get_settings().database_url)
            .update_query_dict(
                {
                    "options": f"-csearch_path={schema}",
                }
            )
            .render_as_string(hide_password=False)
        )
        isolated_settings = get_settings().model_copy(update={"database_url": isolated_url})
        monkeypatch.setattr("finsight.core.config.get_settings", lambda: isolated_settings)
        command.upgrade(Config("alembic.ini"), "head")
        test_engine = create_engine(isolated_url)
        try:
            columns = {column["name"] for column in inspect(test_engine).get_columns("async_jobs")}
            assert {
                "idempotency_key",
                "request_sha256",
                "task_payload",
                "status",
                "attempt_count",
                "max_attempts",
                "next_retry_at",
                "knowledge_base_id",
            } <= columns
            with test_engine.connect() as connection:
                assert connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar() == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        finally:
            test_engine.dispose()
    finally:
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
