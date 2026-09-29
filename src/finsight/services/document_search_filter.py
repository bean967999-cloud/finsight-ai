"""Resolve business document metadata to authoritative PostgreSQL IDs."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database.models import Document, KnowledgeBaseDocument

SessionProvider = Callable[[], Session]


class DocumentSearchFilter(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    company_code: str | None = Field(default=None, min_length=1, max_length=32)
    document_type: DocumentType | None = None
    report_year: int | None = Field(default=None, ge=1900, le=2100)
    knowledge_base_id: UUID | None = None

    @property
    def active(self) -> bool:
        return any(
            value is not None
            for value in (
                self.company_code, self.document_type, self.report_year,
                self.knowledge_base_id,
            )
        )


class FilterTooBroadError(ValueError):
    """The selected document set would produce an unsafe Milvus expression."""


class DocumentFilterResolver:
    def __init__(self, session_provider: SessionProvider, *, max_documents: int = 500) -> None:
        if max_documents < 1:
            raise ValueError("max_documents must be positive")
        self._sessions = session_provider
        self._max_documents = max_documents

    def resolve(self, criteria: DocumentSearchFilter) -> tuple[int, ...] | None:
        """None means no filter; an empty tuple means no matching documents."""
        if not criteria.active:
            return None
        statement = select(Document.id)
        if criteria.knowledge_base_id is not None:
            statement = statement.join(
                KnowledgeBaseDocument, KnowledgeBaseDocument.document_id == Document.id
            ).where(KnowledgeBaseDocument.knowledge_base_id == criteria.knowledge_base_id)
        if criteria.company_code is not None:
            statement = statement.where(Document.company_code == criteria.company_code)
        if criteria.document_type is not None:
            statement = statement.where(Document.document_type == criteria.document_type)
        if criteria.report_year is not None:
            statement = statement.where(Document.report_year == criteria.report_year)
        statement = statement.order_by(Document.id).limit(self._max_documents + 1)
        with self._sessions() as session:
            ids = tuple(session.scalars(statement))
        if len(ids) > self._max_documents:
            raise FilterTooBroadError("filter matches too many documents; narrow the criteria")
        return ids
