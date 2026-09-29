"""Idempotent registration of original documents and ingestion jobs."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from hashlib import sha256

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finsight.domain.document_data import (
    DocumentIngestionJobData,
    DocumentIngestionStatus,
    DocumentMetadata,
    DocumentType,
)
from finsight.infrastructure.database.models import Document, DocumentIngestionJob
from finsight.infrastructure.database.repositories.document import DocumentRepository
from finsight.infrastructure.database.repositories.document_ingestion_job import (
    DocumentIngestionJobRepository,
)
from finsight.services.document_deduplication import fingerprint_document
from finsight.services.object_storage import ObjectStorage

SessionProvider = Callable[[], Session]


class DocumentIngestionError(RuntimeError):
    """An ingestion request cannot be completed safely."""


class DocumentIngestionService:
    def __init__(self, session_provider: SessionProvider, storage: ObjectStorage) -> None:
        self._sessions = session_provider
        self._storage = storage

    def ingest(
        self,
        content: bytes,
        *,
        idempotency_key: str,
        title: str,
        document_type: DocumentType,
        company_code: str | None = None,
        security_symbol: str | None = None,
        report_year: int | None = None,
        report_period_end: date | None = None,
        source_url: str | None = None,
        allowed_existing_document_ids: frozenset[int] | None = None,
    ) -> int:
        """Return the job ID; replaying the same request returns the same ID."""
        DocumentIngestionJobData(idempotency_key=idempotency_key)
        fingerprint = fingerprint_document(content)
        metadata = DocumentMetadata(
            title=title,
            document_type=document_type,
            company_code=company_code,
            security_symbol=security_symbol,
            report_year=report_year,
            report_period_end=report_period_end,
            source_url=source_url,
            object_key=fingerprint.object_key,
            content_sha256=fingerprint.content_sha256,
            file_size_bytes=fingerprint.file_size_bytes,
        )
        request_sha256 = sha256(
            json.dumps(metadata.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        ).hexdigest()

        try:
            with self._sessions() as session, session.begin():
                jobs = DocumentIngestionJobRepository(session)
                job = jobs.add(
                    DocumentIngestionJob(
                        idempotency_key=idempotency_key,
                        request_sha256=request_sha256,
                        status=DocumentIngestionStatus.RUNNING,
                        attempt_count=1,
                        started_at=datetime.now(UTC),
                    )
                )
                job_id = job.id
        except IntegrityError:
            return self._replay(idempotency_key, request_sha256)

        try:
            if not self._storage.exists(fingerprint.object_key):
                self._storage.put(fingerprint.object_key, content)
            elif sha256(self._storage.get(fingerprint.object_key)).hexdigest() != (
                fingerprint.content_sha256
            ):
                raise DocumentIngestionError("Stored object does not match its content key")

            try:
                with self._sessions() as session, session.begin():
                    documents = DocumentRepository(session)
                    existing = documents.get_by_content_sha256(fingerprint.content_sha256)
                    if existing is None:
                        document = documents.add(Document(**metadata.model_dump()))
                        document_id = document.id
                    else:
                        if allowed_existing_document_ids is not None and existing.document_id not in allowed_existing_document_ids:
                            raise DocumentIngestionError("Existing document is outside authorized scope")
                        document_id = existing.document_id
                    self._mark_succeeded(session, job_id, document_id)
            except IntegrityError:
                # Another request may have committed the same content concurrently.
                with self._sessions() as session, session.begin():
                    existing = DocumentRepository(session).get_by_content_sha256(
                        fingerprint.content_sha256
                    )
                    if existing is None:
                        raise
                    if allowed_existing_document_ids is not None and existing.document_id not in allowed_existing_document_ids:
                        raise DocumentIngestionError("Concurrent duplicate is outside authorized scope")
                    self._mark_succeeded(session, job_id, existing.document_id)
        except Exception as exc:
            self._mark_failed(job_id, type(exc).__name__)
            raise DocumentIngestionError("Document ingestion failed; job marked failed") from exc
        return job_id

    def _replay(self, key: str, request_sha256: str) -> int:
        with self._sessions() as session:
            job = DocumentIngestionJobRepository(session).get_by_idempotency_key(key)
            if job is None:
                raise DocumentIngestionError("Idempotency conflict; job not visible yet")
            if job.request_sha256 != request_sha256:
                raise DocumentIngestionError("Idempotency key belongs to a different request")
            if job.status != DocumentIngestionStatus.SUCCEEDED:
                raise DocumentIngestionError(f"Existing ingestion job is {job.status.value}")
            return job.id

    @staticmethod
    def _mark_succeeded(session: Session, job_id: int, document_id: int) -> None:
        job = DocumentIngestionJobRepository(session).get(job_id)
        if job is None:
            raise DocumentIngestionError("Ingestion job disappeared")
        job.document_id = document_id
        job.status = DocumentIngestionStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)

    def _mark_failed(self, job_id: int, error_code: str) -> None:
        with self._sessions() as session, session.begin():
            job = DocumentIngestionJobRepository(session).get(job_id)
            if job is None:
                raise DocumentIngestionError("Ingestion job disappeared")
            job.status = DocumentIngestionStatus.FAILED
            job.error_code = error_code[:100]
            job.finished_at = datetime.now(UTC)
