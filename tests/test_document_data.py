from datetime import date

import pytest
from pydantic import ValidationError

from finsight.domain.document_data import (
    DocumentChunkMetadata,
    DocumentIngestionJobData,
    DocumentMetadata,
    DocumentType,
)


def test_annual_report_requires_traceable_company_period_and_file():
    document = DocumentMetadata(
        title="演示银行 2024 年年度报告",
        document_type=DocumentType.ANNUAL_REPORT,
        company_code="DEMO.SH",
        security_symbol="999998.SH",
        report_year=2024,
        report_period_end=date(2024, 12, 31),
        source_url="https://example.test/report.pdf",
        object_key="annual/2024/demo.pdf",
        content_sha256="a" * 64,
        file_size_bytes=1024,
    )
    assert document.report_year == document.report_period_end.year
    assert document.mime_type == "application/pdf"
    with pytest.raises(ValidationError):
        document.title = "changed"


@pytest.mark.parametrize(
    "invalid_change",
    [
        {"company_code": None},
        {"report_year": 2023},
        {"content_sha256": "bad"},
        {"object_key": "../outside.pdf"},
        {"file_size_bytes": 0},
    ],
)
def test_document_rejects_missing_or_unsafe_metadata(invalid_change):
    values = {
        "title": "演示年报",
        "document_type": "annual_report",
        "company_code": "DEMO.SH",
        "report_year": 2024,
        "report_period_end": date(2024, 12, 31),
        "object_key": "annual/2024/demo.pdf",
        "content_sha256": "a" * 64,
        "file_size_bytes": 1024,
    }
    values.update(invalid_change)
    with pytest.raises(ValidationError):
        DocumentMetadata(**values)


def test_regulatory_document_does_not_require_company_or_report_period():
    document = DocumentMetadata(
        title="演示监管文件",
        document_type=DocumentType.REGULATORY_POLICY,
        object_key="regulatory/demo.pdf",
        content_sha256="b" * 64,
        file_size_bytes=512,
    )
    assert document.company_code is None
    assert document.report_period_end is None


def test_chunk_page_range_and_version_are_validated():
    chunk = DocumentChunkMetadata(
        document_id=1,
        chunk_index=0,
        chunk_version=1,
        page_start=12,
        page_end=13,
        section_title="管理层讨论",
        content_sha256="c" * 64,
    )
    assert chunk.page_start == 12
    with pytest.raises(ValidationError, match="page_end must not be before"):
        DocumentChunkMetadata(
            document_id=1, chunk_index=0, page_start=13, page_end=12,
            content_sha256="c" * 64,
        )


def test_ingestion_job_starts_pending_and_requires_idempotency_key():
    job = DocumentIngestionJobData(idempotency_key="document-demo-2024")
    assert job.status.value == "pending"
    assert job.attempt_count == 0
    with pytest.raises(ValidationError):
        DocumentIngestionJobData(idempotency_key="")
