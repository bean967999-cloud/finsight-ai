from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import (
    Document,
    KnowledgeBase,
    KnowledgeBaseDocument,
    Workspace,
)
from finsight.services.document_search_filter import (
    DocumentFilterResolver,
    DocumentSearchFilter,
    FilterTooBroadError,
)


@pytest.fixture
def resolver():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session)
    records = [
        ("AAA", DocumentType.ANNUAL_REPORT, 2024),
        ("AAA", DocumentType.ANNUAL_REPORT, 2023),
        ("BBB", DocumentType.ANNUAL_REPORT, 2024),
        ("AAA", DocumentType.ANNOUNCEMENT, 2024),
    ]
    with sessions() as session, session.begin():
        for index, (company, kind, year) in enumerate(records):
            session.add(Document(
                title=f"Report {index}", document_type=kind, company_code=company,
                report_year=year,
                report_period_end=date(year, 12, 31) if kind == DocumentType.ANNUAL_REPORT else None,
                object_key=f"documents/{index}.pdf", content_sha256=f"{index:064x}",
                file_size_bytes=10,
            ))
    yield DocumentFilterResolver(sessions), sessions
    engine.dispose()


def test_combined_business_filters_are_intersection(resolver) -> None:
    service, _ = resolver
    assert service.resolve(DocumentSearchFilter(
        company_code="AAA", document_type=DocumentType.ANNUAL_REPORT, report_year=2024,
    )) == (1,)
    assert service.resolve(DocumentSearchFilter(company_code="AAA", report_year=2024)) == (1, 4)
    assert service.resolve(DocumentSearchFilter(company_code="UNKNOWN")) == ()
    assert service.resolve(DocumentSearchFilter()) is None


def test_broad_filter_fails_instead_of_silently_truncating(resolver) -> None:
    _, sessions = resolver
    service = DocumentFilterResolver(sessions, max_documents=1)
    with pytest.raises(FilterTooBroadError, match="too many"):
        service.resolve(DocumentSearchFilter(report_year=2024))


def test_invalid_filter_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DocumentSearchFilter(company_code=" ")
    with pytest.raises(ValidationError):
        DocumentSearchFilter(report_year=1800)


def test_knowledge_base_filter_intersects_metadata_and_excludes_unassigned_documents(resolver) -> None:
    service, sessions = resolver
    with sessions() as session, session.begin():
        workspace = Workspace(name=f"team-{uuid4()}")
        session.add(workspace)
        session.flush()
        first = KnowledgeBase(workspace_id=workspace.id, name="first")
        second = KnowledgeBase(workspace_id=workspace.id, name="second")
        session.add_all((first, second))
        session.flush()
        session.add_all((
            KnowledgeBaseDocument(knowledge_base_id=first.id, document_id=1),
            KnowledgeBaseDocument(knowledge_base_id=second.id, document_id=3),
        ))
        first_id, second_id = first.id, second.id
    assert service.resolve(DocumentSearchFilter(knowledge_base_id=first_id)) == (1,)
    assert service.resolve(DocumentSearchFilter(knowledge_base_id=second_id)) == (3,)
    assert service.resolve(DocumentSearchFilter(
        knowledge_base_id=first_id, company_code="BBB"
    )) == ()
    assert service.resolve(DocumentSearchFilter(knowledge_base_id=uuid4())) == ()
