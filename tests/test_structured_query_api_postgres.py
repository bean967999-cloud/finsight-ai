"""Opt-in real HTTP-to-PostgreSQL structured query acceptance."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.api.routes.structured_query import get_structured_query
from finsight.core.config import get_settings
from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialStatementRecord,
    MarketPriceRecord,
    SecurityRecord,
)
from finsight.infrastructure.database import Base
from finsight.main import app
from finsight.services.data_quality import FinancialDataBatch
from finsight.services.financial_import import FinancialImportService
from finsight.services.read_only_query_executor import ReadOnlyQueryExecutor
from finsight.services.structured_query import StructuredQueryService

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 to run against local PostgreSQL",
)


def test_real_structured_query_api_for_statement_indicator_price_and_empty_result() -> None:
    database_url = get_settings().database_url
    schema = f"finsight_query_api_{uuid4().hex[:12]}"
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
        origin = {"source_code": "api_fixture", "source_record_id": "api:1"}
        FinancialImportService(sessions).import_batch(
            FinancialDataBatch(
                companies=(CompanyRecord(
                    **origin, company_code="API_DEMO", legal_name="接口验收公司",
                ),),
                securities=(SecurityRecord(
                    **origin, company_code="API_DEMO", exchange="SSE",
                    ticker="999997", name="接口验收证券",
                ),),
                market_prices=(
                    MarketPriceRecord(
                        **origin, exchange="SSE", ticker="999997",
                        trade_date=date(2025, 1, 2), open_price=Decimal(10),
                        high_price=Decimal(12), low_price=Decimal(9),
                        close_price=Decimal(11), volume=Decimal(100),
                    ),
                    MarketPriceRecord(
                        **{**origin, "source_record_id": "api:2"},
                        exchange="SSE", ticker="999997", trade_date=date(2025, 1, 3),
                        open_price=Decimal(11), high_price=Decimal(13),
                        low_price=Decimal(10), close_price=Decimal(12), volume=Decimal(120),
                    ),
                ),
                financial_statements=(FinancialStatementRecord(
                    **origin, company_code="API_DEMO", report_date=date(2024, 12, 31),
                    period_type="annual", statement_type="income_statement",
                    item_code="revenue", item_name="营业收入", value=Decimal("456.78"),
                ),),
                financial_indicators=(FinancialIndicatorRecord(
                    **origin, company_code="API_DEMO", report_date=date(2024, 12, 31),
                    period_type="annual", indicator_code="roe", indicator_name="净资产收益率",
                    value=Decimal("12.5"), unit="%",
                ),),
            ),
            source_code="api_fixture", idempotency_key="api-fixture",
        )
        service = StructuredQueryService(ReadOnlyQueryExecutor(sessions))
        app.dependency_overrides[get_structured_query] = lambda: service
        client = TestClient(app)

        statement = client.post("/api/v1/query/structured", json={
            "query": "查询 API_DEMO 2024 年营业收入",
            "intent": "financial_statement",
            "entities": {"company_codes": ["API_DEMO"]},
            "metrics": [{"term": "营业收入"}],
            "time": {"report_years": [2024]},
            "period_type": "annual",
            "statement_type": "income_statement",
            "limit": 10,
        })
        indicator = client.post("/api/v1/query/structured", json={
            "query": "查询 API_DEMO 2024 年 ROE",
            "intent": "financial_indicator",
            "entities": {"company_codes": ["API_DEMO"]},
            "metrics": [{"term": "ROE"}],
            "time": {"report_years": [2024]},
            "period_type": "annual",
            "limit": 10,
        })
        price = client.post("/api/v1/query/structured", json={
            "query": "查询 999997 的平均收盘价",
            "intent": "market_price",
            "entities": {"tickers": ["999997"], "exchanges": ["SSE"]},
            "metrics": [{"term": "收盘价", "aggregation": "average"}],
            "time": {"start_date": "2025-01-01", "end_date": "2025-01-31"},
            "limit": 10,
        })
        empty = client.post("/api/v1/query/structured", json={
            "query": "查询不存在公司的营业收入",
            "intent": "financial_statement",
            "entities": {"company_codes": ["NOT_FOUND"]},
            "metrics": [{"term": "营业收入"}],
            "time": {"report_years": [2024]},
            "limit": 10,
        })

        assert statement.status_code == indicator.status_code == price.status_code == 200
        assert empty.status_code == 200
        assert statement.json()["rows"][0]["value"] == "456.780000"
        assert statement.json()["rows"][0]["unit"] == "yuan"
        assert indicator.json()["rows"][0]["value"] == "12.5000000000"
        assert indicator.json()["rows"][0]["unit"] == "%"
        assert price.json()["rows"][0]["average_close_price"] == "11.5000000000000000"
        assert empty.json()["row_count"] == 0 and empty.json()["rows"] == []
        assert all(response.json()["execution_ms"] >= 0 for response in (
            statement, indicator, price, empty,
        ))
    finally:
        app.dependency_overrides.clear()
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
