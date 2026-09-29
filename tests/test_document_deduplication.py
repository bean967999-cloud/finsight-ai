from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document
from finsight.infrastructure.database.repositories.document import DocumentRepository
from finsight.services.document_deduplication import (
    DocumentDuplicateChecker,
    EmptyDocumentError,
    ExistingDocument,
    fingerprint_document,
)


class FakeDocumentLookup:
    def __init__(self, existing: ExistingDocument | None = None) -> None:
        self.existing = existing
        self.last_digest: str | None = None

    def get_by_content_sha256(self, digest: str) -> ExistingDocument | None:
        self.last_digest = digest
        return self.existing


def test_fingerprint_is_based_on_bytes_not_filename() -> None:
    content = b"%PDF-1.7\nfinancial report"

    first = fingerprint_document(content)
    second = fingerprint_document(content)

    assert first == second
    assert len(first.content_sha256) == 64
    assert first.file_size_bytes == len(content)
    assert first.object_key == (
        f"documents/sha256/{first.content_sha256[:2]}/{first.content_sha256}.pdf"
    )
    assert fingerprint_document(content + b" updated").content_sha256 != first.content_sha256


def test_empty_content_is_rejected() -> None:
    with pytest.raises(EmptyDocumentError):
        fingerprint_document(b"")


def test_checker_reports_new_document_without_writing() -> None:
    lookup = FakeDocumentLookup()
    result = DocumentDuplicateChecker(lookup).check(b"%PDF-1.7\nnew")

    assert result.is_duplicate is False
    assert result.existing_document is None
    assert lookup.last_digest == result.fingerprint.content_sha256


def test_checker_returns_existing_document() -> None:
    fingerprint = fingerprint_document(b"%PDF-1.7\nexisting")
    existing = ExistingDocument(
        document_id=42,
        content_sha256=fingerprint.content_sha256,
        file_size_bytes=fingerprint.file_size_bytes,
        object_key=fingerprint.object_key,
    )

    result = DocumentDuplicateChecker(FakeDocumentLookup(existing)).check(
        b"%PDF-1.7\nexisting"
    )

    assert result.is_duplicate is True
    assert result.existing_document == existing


def test_repository_looks_up_persisted_document_by_checksum() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    content = b"%PDF-1.7\nannual report"
    fingerprint = fingerprint_document(content)

    with Session(engine) as session:
        repository = DocumentRepository(session)
        assert repository.get_by_content_sha256(fingerprint.content_sha256) is None
        document = repository.add(
            Document(
                title="Example Annual Report",
                document_type="annual_report",
                company_code="CMB",
                report_year=2025,
                report_period_end=date(2025, 12, 31),
                object_key=fingerprint.object_key,
                content_sha256=fingerprint.content_sha256,
                file_size_bytes=fingerprint.file_size_bytes,
            )
        )
        result = DocumentDuplicateChecker(repository).check(content)

        assert result.is_duplicate is True
        assert result.existing_document is not None
        assert result.existing_document.document_id == document.id
        assert result.existing_document.object_key == fingerprint.object_key
        assert session.query(Document).count() == 1

    engine.dispose()
