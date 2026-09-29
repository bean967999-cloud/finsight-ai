"""Opt-in integration test against a disposable schema in real PostgreSQL."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialStatementRecord,
    MarketPriceRecord,
    SecurityRecord,
)
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import (
    Company,
    FinancialIndicator,
    FinancialStatement,
    ImportJob,
    MarketPrice,
    Security,
)
from finsight.services.data_quality import FinancialDataBatch
from finsight.services.financial_import import FinancialImportService

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 to run against local PostgreSQL",
)


def test_real_postgres_import_replay_and_new_version():
    database_url = get_settings().database_url
    schema = f"finsight_step8_{uuid4().hex[:12]}"
    admin_engine = create_engine(database_url)
    test_engine = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True

        test_engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        service = FinancialImportService(sessions)

        origin = {"source_code": "csv_demo", "source_record_id": "postgres-fixture:1"}
        batch = FinancialDataBatch(
            companies=(CompanyRecord(
                **origin, company_code="STEP8_DEMO", legal_name="Step 8 演示公司"
            ),),
            securities=(SecurityRecord(
                **origin, company_code="STEP8_DEMO", exchange="SSE",
                ticker="999998", name="Step 8 演示证券"
            ),),
            market_prices=(MarketPriceRecord(
                **origin, exchange="SSE", ticker="999998", trade_date=date(2025, 1, 2),
                open_price=Decimal(10), high_price=Decimal(11), low_price=Decimal(9),
                close_price=Decimal(10), volume=Decimal(100),
            ),),
            financial_statements=(FinancialStatementRecord(
                **origin, company_code="STEP8_DEMO", report_date=date(2024, 12, 31),
                period_type="annual", statement_type="income_statement",
                item_code="revenue", item_name="演示收入", value=Decimal(100),
            ),),
            financial_indicators=(FinancialIndicatorRecord(
                **origin, company_code="STEP8_DEMO", report_date=date(2024, 12, 31),
                period_type="annual", indicator_code="roe", indicator_name="演示 ROE",
                value=Decimal("12.5"), unit="%",
            ),),
        )

        first_id = service.import_batch(batch, source_code="csv_demo", idempotency_key="step8-a")
        replay_id = service.import_batch(batch, source_code="csv_demo", idempotency_key="step8-b")
        version_two = FinancialDataBatch(financial_statements=(
            batch.financial_statements[0].model_copy(
                update={"data_version": 2, "value": Decimal(110)}
            ),
        ))
        version_id = service.import_batch(
            version_two, source_code="csv_demo", idempotency_key="step8-c"
        )

        with sessions() as session:
            first = session.get(ImportJob, first_id)
            replay = session.get(ImportJob, replay_id)
            version = session.get(ImportJob, version_id)
            assert first is not None and (first.rows_inserted, first.rows_updated) == (5, 0)
            assert replay is not None and (replay.rows_inserted, replay.rows_updated) == (0, 0)
            assert version is not None and (version.rows_inserted, version.rows_updated) == (1, 0)
            assert [session.scalar(select(func.count()).select_from(model)) for model in (
                Company, Security, MarketPrice, FinancialStatement, FinancialIndicator
            )] == [1, 1, 1, 2, 1]
            assert [row.data_version for row in session.scalars(
                select(FinancialStatement).order_by(FinancialStatement.data_version)
            )] == [1, 2]
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
