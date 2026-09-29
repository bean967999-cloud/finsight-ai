"""Load only a completed, matching parsed document for chunk generation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError
from sqlalchemy.orm import Session

from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.domain.parsed_document import ParsedDocument
from finsight.infrastructure.database.models import Document, DocumentParseJob
from finsight.services.object_storage import ObjectStorage, ObjectStorageError

SessionProvider = Callable[[], Session]


class ChunkSourceError(RuntimeError):
    """The requested parse attempt cannot safely supply chunks."""


@dataclass(frozen=True, slots=True)
class ChunkSource:
    parse_job_id: int
    document_id: int
    source_sha256: str
    parsed_document: ParsedDocument
    title: str
    document_type: DocumentType
    company_code: str | None
    security_symbol: str | None
    report_year: int | None
    report_period_end: date | None
    source_url: str | None


class ChunkSourceLoader:
    def __init__(self, session_provider: SessionProvider, storage: ObjectStorage) -> None:
        self._sessions = session_provider
        self._storage = storage

    def load(self, parse_job_id: int) -> ChunkSource:
        """Use an explicit parse attempt, never an ambiguous latest result."""
        if parse_job_id <= 0:
            raise ValueError("parse_job_id must be positive")
        with self._sessions() as session:
            job = session.get(DocumentParseJob, parse_job_id)
            if job is None:
                raise ChunkSourceError("Parse job does not exist")
            if job.status != DocumentParseStatus.SUCCEEDED:
                raise ChunkSourceError("Parse job is not succeeded")
            document = session.get(Document, job.document_id)
            if document is None:
                raise ChunkSourceError("Source document does not exist")
            if job.source_sha256 != document.content_sha256:
                raise ChunkSourceError("Parse job does not match source document")
            if not job.parsed_document_key or not job.parser_name or not job.parser_version:
                raise ChunkSourceError("Parse job is missing required result metadata")

            try:
                content = self._storage.get(job.parsed_document_key)
                parsed = ParsedDocument.model_validate_json(content)
            except (ObjectStorageError, OSError, ValidationError) as exc:
                raise ChunkSourceError("Parsed document artifact is unavailable or invalid") from exc
            if (
                parsed.document_id != document.id
                or parsed.source_sha256 != job.source_sha256
                or parsed.parser_name != job.parser_name
                or parsed.parser_version != job.parser_version
                or parsed.page_count != job.page_count
            ):
                raise ChunkSourceError("Parsed document artifact does not match parse job")
            return ChunkSource(
                parse_job_id=job.id,
                document_id=document.id,
                source_sha256=document.content_sha256,
                parsed_document=parsed,
                title=document.title,
                document_type=document.document_type,
                company_code=document.company_code,
                security_symbol=document.security_symbol,
                report_year=document.report_year,
                report_period_end=document.report_period_end,
                source_url=document.source_url,
            )
