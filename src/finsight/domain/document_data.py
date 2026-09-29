"""Source-neutral contracts for financial documents and ingestion jobs."""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentType(StrEnum):
    ANNUAL_REPORT = "annual_report"
    SEMIANNUAL_REPORT = "semiannual_report"
    QUARTERLY_REPORT = "quarterly_report"
    ANNOUNCEMENT = "announcement"
    REGULATORY_POLICY = "regulatory_policy"


class DocumentIngestionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentParseStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentMetadata(BaseModel):
    """Metadata for one stored PDF; no parsing or vector data is implied."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    document_type: DocumentType
    company_code: str | None = Field(default=None, max_length=32)
    security_symbol: str | None = Field(default=None, max_length=50)
    report_year: int | None = Field(default=None, ge=1900, le=2100)
    report_period_end: date | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    object_key: str = Field(min_length=1, max_length=500)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_size_bytes: int = Field(gt=0)
    mime_type: Literal["application/pdf"] = "application/pdf"

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        parts = value.replace("\\", "/").split("/")
        if value.startswith(("/", "\\")) or ":" in value or ".." in parts or "" in parts:
            raise ValueError("object_key must be a relative storage key")
        return value

    @model_validator(mode="after")
    def validate_report_metadata(self) -> "DocumentMetadata":
        report_types = {
            DocumentType.ANNUAL_REPORT,
            DocumentType.SEMIANNUAL_REPORT,
            DocumentType.QUARTERLY_REPORT,
        }
        if self.document_type in report_types:
            if not self.company_code or not self.report_period_end or self.report_year is None:
                raise ValueError("company_code, report_year and report_period_end are required")
            if self.report_year != self.report_period_end.year:
                raise ValueError("report_year must match report_period_end")
        return self


class DocumentChunkMetadata(BaseModel):
    """Stable citation and version fields for one future parsed chunk."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    document_id: int = Field(gt=0)
    chunk_index: int = Field(ge=0)
    chunk_version: int = Field(default=1, ge=1)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    section_title: str | None = Field(default=None, max_length=500)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_page_range(self) -> "DocumentChunkMetadata":
        if self.page_end < self.page_start:
            raise ValueError("page_end must not be before page_start")
        return self


class DocumentIngestionJobData(BaseModel):
    """Trace one document ingestion request independently of import_jobs."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=1, max_length=128)
    document_id: int | None = Field(default=None, gt=0)
    status: DocumentIngestionStatus = DocumentIngestionStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=100)
