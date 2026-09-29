from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialQuery,
    FinancialStatementRecord,
    MarketPriceQuery,
    MarketPriceRecord,
    SecurityRecord,
)
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import (
    Company,
    DataSource,
    FinancialIndicator,
    FinancialStatement,
    ImportJob,
    MarketPrice,
    Security,
)
from finsight.services.data_quality import FinancialDataBatch
from finsight.services.financial_import import FinancialImportError, FinancialImportService


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    yield factory
    engine.dispose()


def example_batch() -> FinancialDataBatch:
    origin = {"source_code": "csv_demo", "source_record_id": "fixture:1"}
    return FinancialDataBatch(
        companies=(CompanyRecord(**origin, company_code="CMB", legal_name="演示公司"),),
        securities=(SecurityRecord(
            **origin, company_code="CMB", exchange="SSE", ticker="600036", name="演示证券"
        ),),
        market_prices=(MarketPriceRecord(
            **origin, exchange="SSE", ticker="600036", trade_date=date(2025, 1, 2),
            open_price=Decimal(10), high_price=Decimal(11), low_price=Decimal(9),
            close_price=Decimal(10), volume=Decimal(100),
        ),),
        financial_statements=(FinancialStatementRecord(
            **origin, company_code="CMB", report_date=date(2024, 12, 31),
            period_type="annual", statement_type="income_statement", item_code="revenue",
            item_name="演示收入", value=Decimal(100),
        ),),
        financial_indicators=(FinancialIndicatorRecord(
            **origin, company_code="CMB", report_date=date(2024, 12, 31),
            period_type="annual", indicator_code="roe", indicator_name="演示ROE",
            value=Decimal("12.5"), unit="%",
        ),),
    )


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_import_commits_five_business_rows_and_job(sessions):
    job_id = FinancialImportService(sessions).import_batch(
        example_batch(), source_code="csv_demo", idempotency_key="first-batch"
    )
    with sessions() as session:
        assert [count(session, model) for model in (
            Company, Security, MarketPrice, FinancialStatement, FinancialIndicator
        )] == [1, 1, 1, 1, 1]
        assert count(session, DataSource) == 1
        job = session.get(ImportJob, job_id)
        assert job is not None
        assert job.status.value == "succeeded"
        assert (job.rows_received, job.rows_inserted, job.rows_updated) == (5, 5, 0)
        assert job.finished_at is not None


def test_quality_error_records_failed_job_without_business_rows(sessions):
    batch = example_batch()
    wrong_unit = batch.financial_indicators[0].model_copy(update={"unit": "ratio"})
    bad_batch = FinancialDataBatch(
        companies=batch.companies, financial_indicators=(wrong_unit,)
    )
    with pytest.raises(FinancialImportError, match="Quality validation failed"):
        FinancialImportService(sessions).import_batch(
            bad_batch, source_code="csv_demo", idempotency_key="bad-quality"
        )
    with sessions() as session:
        assert count(session, Company) == 0
        job = session.scalar(select(ImportJob))
        assert job is not None and job.status.value == "failed"
        assert job.rows_inserted == 0


def test_database_error_rolls_back_whole_business_batch(sessions):
    service = FinancialImportService(sessions)
    service.import_batch(example_batch(), source_code="csv_demo", idempotency_key="first")
    original = example_batch()
    changed_company = original.companies[0].model_copy(update={"legal_name": "不应提交的名称"})
    missing_security_price = original.market_prices[0].model_copy(update={"ticker": "999999"})
    failing_batch = FinancialDataBatch(
        companies=(changed_company,), market_prices=(missing_security_price,)
    )
    with pytest.raises(FinancialImportError, match="rolled back"):
        service.import_batch(failing_batch, source_code="csv_demo", idempotency_key="second")
    with sessions() as session:
        assert count(session, Company) == 1
        assert count(session, MarketPrice) == 1
        assert session.scalar(select(Company.legal_name)) == "演示公司"
        jobs = list(session.scalars(select(ImportJob).order_by(ImportJob.id)))
        assert [job.status.value for job in jobs] == ["succeeded", "failed"]


def test_unchanged_reimport_does_not_duplicate_or_update_rows(sessions):
    service = FinancialImportService(sessions)
    service.import_batch(example_batch(), source_code="csv_demo", idempotency_key="first")
    job_id = service.import_batch(
        example_batch(), source_code="csv_demo", idempotency_key="second"
    )
    with sessions() as session:
        job = session.get(ImportJob, job_id)
        assert job is not None
        assert (job.rows_received, job.rows_inserted, job.rows_updated) == (5, 0, 0)
        assert count(session, Company) == 1
        assert count(session, MarketPrice) == 1


def test_changed_same_version_updates_existing_rows(sessions):
    service = FinancialImportService(sessions)
    service.import_batch(example_batch(), source_code="csv_demo", idempotency_key="first")
    original = example_batch()
    changed = FinancialDataBatch(
        companies=(original.companies[0].model_copy(update={"legal_name": "修订名称"}),),
        securities=original.securities,
        market_prices=(
            original.market_prices[0].model_copy(update={"close_price": Decimal("10.5")}),
        ),
        financial_statements=(
            original.financial_statements[0].model_copy(update={"value": Decimal(110)}),
        ),
        financial_indicators=(
            original.financial_indicators[0].model_copy(update={"value": Decimal(13)}),
        ),
    )
    job_id = service.import_batch(changed, source_code="csv_demo", idempotency_key="revision")
    with sessions() as session:
        job = session.get(ImportJob, job_id)
        assert job is not None
        assert (job.rows_inserted, job.rows_updated) == (0, 4)
        assert session.scalar(select(Company.legal_name)) == "修订名称"
        assert session.scalar(select(MarketPrice.close_price)) == Decimal("10.5")
        assert session.scalar(select(FinancialStatement.value)) == Decimal(110)
        assert count(session, FinancialIndicator) == 1


def test_new_data_version_preserves_previous_financial_record(sessions):
    service = FinancialImportService(sessions)
    service.import_batch(example_batch(), source_code="csv_demo", idempotency_key="first")
    original = example_batch()
    version_two = FinancialDataBatch(
        financial_statements=(original.financial_statements[0].model_copy(
            update={"data_version": 2, "value": Decimal(110)}
        ),),
    )
    job_id = service.import_batch(
        version_two, source_code="csv_demo", idempotency_key="version-two"
    )
    with sessions() as session:
        job = session.get(ImportJob, job_id)
        assert job is not None and (job.rows_inserted, job.rows_updated) == (1, 0)
        statements = list(session.scalars(select(FinancialStatement).order_by(
            FinancialStatement.data_version
        )))
        assert [(row.data_version, row.value) for row in statements] == [
            (1, Decimal(100)), (2, Decimal(110))
        ]


def test_same_idempotency_key_does_not_start_second_import(sessions):
    service = FinancialImportService(sessions)
    service.import_batch(example_batch(), source_code="csv_demo", idempotency_key="once")
    with pytest.raises(FinancialImportError, match="idempotency_key already exists"):
        service.import_batch(example_batch(), source_code="csv_demo", idempotency_key="once")
    with sessions() as session:
        assert count(session, ImportJob) == 1


def test_service_fetches_from_provider_before_import(sessions):
    batch = example_batch()

    class Provider:
        source_code = "csv_demo"

        def fetch_companies(self, codes):
            return list(batch.companies)

        def fetch_securities(self, codes):
            return list(batch.securities)

        def fetch_market_prices(self, query):
            return list(batch.market_prices)

        def fetch_financial_statements(self, query):
            return list(batch.financial_statements)

        def fetch_financial_indicators(self, query):
            return list(batch.financial_indicators)

    job_id = FinancialImportService(sessions).import_from_provider(
        Provider(),
        company_codes=["CMB"],
        market_query=MarketPriceQuery(
            symbols=("600036.SH",), start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)
        ),
        financial_query=FinancialQuery(
            company_codes=("CMB",), start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        ),
        idempotency_key="provider-import",
    )
    with sessions() as session:
        job = session.get(ImportJob, job_id)
        assert job is not None and job.rows_inserted == 5


def test_provider_failure_is_recorded_without_business_rows(sessions):
    class FailingProvider:
        source_code = "csv_demo"

        def fetch_companies(self, codes):
            raise RuntimeError("private provider details")

        def fetch_securities(self, codes):
            return []

        def fetch_market_prices(self, query):
            return []

        def fetch_financial_statements(self, query):
            return []

        def fetch_financial_indicators(self, query):
            return []

    with pytest.raises(FinancialImportError, match="Provider fetch failed"):
        FinancialImportService(sessions).import_from_provider(
            FailingProvider(),
            company_codes=["CMB"],
            market_query=MarketPriceQuery(
                symbols=("600036.SH",), start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
            ),
            financial_query=FinancialQuery(
                company_codes=("CMB",), start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
            ),
            idempotency_key="fetch-failed",
        )
    with sessions() as session:
        assert count(session, Company) == 0
        job = session.scalar(select(ImportJob))
        assert job is not None and job.status.value == "failed"
        assert job.rows_received == 0
        assert "private provider details" not in (job.error_message or "")
