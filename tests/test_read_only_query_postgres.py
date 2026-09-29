"""Opt-in real PostgreSQL acceptance for guarded read-only execution."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.financial_data import CompanyRecord, FinancialStatementRecord
from finsight.domain.query_plan import (
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    TimeSelection,
)
from finsight.infrastructure.database import Base
from finsight.security.structured_query_guard import guard_compiled_query
from finsight.services.data_quality import FinancialDataBatch
from finsight.services.financial_import import FinancialImportService
from finsight.services.metric_resolution import MetricResolver
from finsight.services.query_compiler import QueryCompiler
from finsight.services.query_planning import build_query_plan
from finsight.services.query_schema_context import build_financial_query_schema
from finsight.services.read_only_query_executor import ReadOnlyQueryExecutor

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 to run against local PostgreSQL",
)


def test_real_postgres_guarded_read_only_query() -> None:
    database_url = get_settings().database_url
    schema = f"finsight_query_{uuid4().hex[:12]}"
    admin_engine = create_engine(database_url)
    test_engine = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        test_engine = create_engine(
            database_url, connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        origin = {"source_code": "query_fixture", "source_record_id": "query:1"}
        FinancialImportService(sessions).import_batch(
            FinancialDataBatch(
                companies=(CompanyRecord(
                    **origin, company_code="QUERY_DEMO", legal_name="查询演示公司",
                ),),
                financial_statements=(FinancialStatementRecord(
                    **origin, company_code="QUERY_DEMO", report_date=date(2024, 12, 31),
                    period_type="annual", statement_type="income_statement",
                    item_code="revenue", item_name="营业收入", value=Decimal("123.45"),
                ),),
            ),
            source_code="query_fixture", idempotency_key="query-fixture",
        )
        plan = build_query_plan(
            "查询 QUERY_DEMO 2024 年营业收入", status=PlanStatus.READY,
            intent=QueryIntent.FINANCIAL_STATEMENT,
            entities=EntitySelection(company_codes=("QUERY_DEMO",)),
            metrics=(MetricRequest(term="营业收入"),),
            time=TimeSelection(report_years=(2024,)), limit=10,
        )
        compiled = QueryCompiler().compile(plan, MetricResolver().resolve_plan(plan))
        guarded = guard_compiled_query(compiled, build_financial_query_schema())
        result = ReadOnlyQueryExecutor(sessions, statement_timeout_ms=2_000).execute(guarded)
        assert result.row_count == 1
        assert result.rows[0]["company_code"] == "QUERY_DEMO"
        assert result.rows[0]["item_code"] == "revenue"
        assert result.rows[0]["value"] == Decimal("123.450000")

        with pytest.raises(DBAPIError), sessions() as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("UPDATE companies SET legal_name = 'blocked'"))
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
