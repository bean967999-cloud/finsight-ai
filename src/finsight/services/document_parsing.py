"""Persist one PDF parse attempt without changing original ingestion state."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy.orm import Session

from finsight.domain.document_data import DocumentParseStatus
from finsight.domain.parsed_document import ParsedDocument
from finsight.infrastructure.database.models import Document, DocumentParseJob
from finsight.services.document_parser import DocumentParser, ParserOutput
from finsight.services.object_storage import ObjectStorage, ObjectStorageError

logger = logging.getLogger(__name__)

SessionProvider = Callable[[], Session]
DocumentNormalizer = Callable[[ParserOutput, int], ParsedDocument]


class DocumentParsingError(RuntimeError):
    """An attempt failed; the independent parse job records its failure code."""


class DocumentParsingService:
    def __init__(
        self,
        session_provider: SessionProvider,
        storage: ObjectStorage,
        parser: DocumentParser,
        normalizer: DocumentNormalizer,
    ) -> None:
        self._sessions = session_provider
        self._storage = storage
        self._parser = parser
        self._normalizer = normalizer

    def parse_document(self, document_id: int) -> int:
        """Return a new parse job ID; each call is a separate attempt."""
        with self._sessions() as session, session.begin():
            document = session.get(Document, document_id)
            if document is None:
                raise DocumentParsingError("Document does not exist")
            source_key = document.object_key
            source_digest = document.content_sha256
            job = DocumentParseJob(
                document_id=document_id,
                status=DocumentParseStatus.RUNNING,
                source_sha256=source_digest,
                started_at=datetime.now(UTC),
            )
            session.add(job)
            session.flush()
            job_id = job.id

        saved_keys: list[str] = []
        try:
            source = self._storage.get(source_key)
            if sha256(source).hexdigest() != source_digest:
                raise DocumentParsingError("Stored PDF does not match its document digest")
            output = self._parser.parse_pdf(source)
            if output.source_sha256 != source_digest:
                raise DocumentParsingError("Parser result does not match the stored PDF")
            parsed = self._normalizer(output, document_id)
            if parsed.document_id != document_id or parsed.source_sha256 != source_digest:
                raise DocumentParsingError("Normalized result does not match the stored PDF")

            prefix = f"parsing/sha256/{source_digest[:2]}/{source_digest}/jobs/{job_id}"
            artifacts = {
                "markdown_key": (f"{prefix}/document.md", parsed.markdown.encode("utf-8")),
                "content_list_key": (
                    f"{prefix}/content-list.json", output.content_list_json.encode("utf-8")
                ),
                "middle_json_key": (f"{prefix}/middle.json", output.middle_json.encode("utf-8")),
                "parsed_document_key": (
                    f"{prefix}/parsed-document.json", parsed.model_dump_json().encode("utf-8")
                ),
            }
            for key, content in artifacts.values():
                self._storage.put(key, content)
                saved_keys.append(key)

            with self._sessions() as session, session.begin():
                completed_job = session.get(DocumentParseJob, job_id)
                if completed_job is None:
                    raise DocumentParsingError("Parse job disappeared")
                completed_job.status = DocumentParseStatus.SUCCEEDED
                completed_job.task_id = output.task_id
                completed_job.parser_name = output.parser_name
                completed_job.parser_version = output.parser_version
                completed_job.page_count = parsed.page_count
                for field_name, (key, _) in artifacts.items():
                    setattr(completed_job, field_name, key)
                completed_job.finished_at = datetime.now(UTC)
        except Exception as exc:
            for key in reversed(saved_keys):
                try:
                    self._storage.delete(key)
                except (ObjectStorageError, OSError):
                    logger.warning("Could not remove partial parse artifact %s", key, exc_info=True)
            self._mark_failed(job_id, type(exc).__name__)
            raise DocumentParsingError("Document parsing failed; job marked failed") from exc
        return job_id

    def _mark_failed(self, job_id: int, error_code: str) -> None:
        with self._sessions() as session, session.begin():
            job = session.get(DocumentParseJob, job_id)
            if job is None:
                raise DocumentParsingError("Parse job disappeared")
            job.status = DocumentParseStatus.FAILED
            job.error_code = error_code[:100]
            job.finished_at = datetime.now(UTC)
