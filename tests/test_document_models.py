from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentChunk, DocumentIngestionJob


def _unique_keys(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_document_tables_and_relationships_are_registered():
    assert {"documents", "document_chunks", "document_ingestion_jobs"} <= set(
        Base.metadata.tables
    )
    assert all(
        model.metadata is Base.metadata
        for model in (Document, DocumentChunk, DocumentIngestionJob)
    )
    configure_mappers()
    assert DocumentChunk.__table__.c.document_id.foreign_keys
    assert DocumentIngestionJob.__table__.c.document_id.foreign_keys


def test_document_checksum_object_key_chunk_version_and_job_key_are_unique():
    assert ("content_sha256",) in _unique_keys("documents")
    assert ("object_key",) in _unique_keys("documents")
    assert ("document_id", "chunk_version", "chunk_index") in _unique_keys(
        "document_chunks"
    )
    assert ("idempotency_key",) in _unique_keys("document_ingestion_jobs")


def test_document_checks_and_audit_columns_exist():
    for table_name in ("documents", "document_chunks", "document_ingestion_jobs"):
        table = Base.metadata.tables[table_name]
        assert {"created_at", "updated_at"} <= set(table.c.keys())
        assert any(isinstance(item, CheckConstraint) for item in table.constraints)


def test_document_enums_store_business_values():
    assert Document.__table__.c.document_type.type.enums == [
        "annual_report", "semiannual_report", "quarterly_report",
        "announcement", "regulatory_policy",
    ]
    assert DocumentIngestionJob.__table__.c.status.type.enums == [
        "pending", "running", "succeeded", "failed",
    ]
