"""Opt-in document ingestion round trip in a disposable PostgreSQL schema."""

import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.document_data import DocumentIngestionStatus, DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentIngestionJob
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.services.document_ingestion import DocumentIngestionService

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 to test local PostgreSQL",
)


def test_real_postgres_document_ingestion_and_replay(tmp_path: Path) -> None:
    database_url = get_settings().database_url
    schema = f"finsight_doc_step7_{uuid4().hex[:12]}"
    admin_engine = create_engine(database_url)
    test_engine = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        test_engine = create_engine(
            database_url, connect_args={"options": f"-csearch_path={schema}"}
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        storage = LocalObjectStorage(tmp_path / "objects")
        service = DocumentIngestionService(sessions, storage)
        content = b"%PDF-1.7\nstep7 document"
        request = {
            "title": "Example Annual Report",
            "document_type": DocumentType.ANNUAL_REPORT,
            "company_code": "CMB",
            "report_year": 2025,
            "report_period_end": date(2025, 12, 31),
        }

        first = service.ingest(content, idempotency_key="step7-first", **request)
        replay = service.ingest(content, idempotency_key="step7-first", **request)
        second = service.ingest(content, idempotency_key="step7-second", **request)

        assert first == replay and second != first
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(Document)) == 1
            assert session.scalar(select(func.count()).select_from(DocumentIngestionJob)) == 2
            jobs = list(session.scalars(select(DocumentIngestionJob)))
            assert all(job.status == DocumentIngestionStatus.SUCCEEDED for job in jobs)
            assert jobs[0].document_id == jobs[1].document_id
            document = session.get(Document, jobs[0].document_id)
            assert document is not None and storage.get(document.object_key) == content
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
