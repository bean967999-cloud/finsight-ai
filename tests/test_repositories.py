from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import (
    Company,
    DataSource,
    FinancialIndicator,
    ImportJob,
    MarketPrice,
    Security,
)
from finsight.infrastructure.database.models.enums import (
    ImportJobStatus,
    ImportJobType,
    ReportingPeriodType,
)
from finsight.infrastructure.database.repositories import (
    CompanyRepository,
    FinancialIndicatorRepository,
    ImportJobRepository,
    MarketPriceRepository,
    SecurityRepository,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as database_session:
        yield database_session

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def master_data(session: Session) -> tuple[Company, DataSource, Security]:
    company = Company(company_code="CMB", legal_name="招商银行股份有限公司")
    source = DataSource(code="csv_demo", name="CSV Demo", provider_type="csv")
    session.add_all([company, source])
    session.flush()

    security = Security(
        company_id=company.id,
        exchange="SSE",
        ticker="600036",
        name="招商银行",
    )
    session.add(security)
    session.commit()
    return company, source, security


def test_repository_add_flushes_without_committing():
    fake_session = Mock(spec=Session)
    company = Company(company_code="PAB", legal_name="平安银行股份有限公司")

    result = CompanyRepository(fake_session).add(company)

    assert result is company
    fake_session.add.assert_called_once_with(company)
    fake_session.flush.assert_called_once_with()
    fake_session.commit.assert_not_called()


def test_company_and_security_business_lookups(
    session: Session,
    master_data: tuple[Company, DataSource, Security],
):
    company, _, security = master_data

    assert CompanyRepository(session).get_by_code("CMB").id == company.id
    assert SecurityRepository(session).get_by_symbol("SSE", "600036").id == security.id
    assert SecurityRepository(session).list_by_company(company.id) == [security]


def test_base_repository_rejects_unbounded_list(session: Session):
    repository = CompanyRepository(session)

    with pytest.raises(ValueError, match="between 1 and 500"):
        repository.list(limit=501)


def test_market_price_query_filters_dates_and_orders_results(
    session: Session,
    master_data: tuple[Company, DataSource, Security],
):
    _, source, security = master_data
    prices = [
        MarketPrice(
            security_id=security.id,
            data_source_id=source.id,
            trade_date=trade_date,
            open_price=Decimal("10.00"),
            high_price=Decimal("11.00"),
            low_price=Decimal("9.50"),
            close_price=close,
            volume=Decimal(1000),
        )
        for trade_date, close in [
            (date(2026, 1, 3), Decimal("10.80")),
            (date(2026, 1, 1), Decimal("10.20")),
            (date(2026, 1, 2), Decimal("10.50")),
        ]
    ]
    session.add_all(prices)
    session.commit()

    result = MarketPriceRepository(session).list_by_security(
        security.id,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
    )

    assert [item.trade_date for item in result] == [date(2026, 1, 2), date(2026, 1, 3)]


def test_financial_indicator_query_filters_codes(
    session: Session,
    master_data: tuple[Company, DataSource, Security],
):
    company, source, _ = master_data
    session.add_all(
        [
            FinancialIndicator(
                company_id=company.id,
                data_source_id=source.id,
                report_date=date(2025, 12, 31),
                period_type=ReportingPeriodType.ANNUAL,
                indicator_code=code,
                indicator_name=name,
                value=value,
                unit="percent",
            )
            for code, name, value in [
                ("roe", "净资产收益率", Decimal("14.20")),
                ("roa", "总资产收益率", Decimal("1.15")),
            ]
        ]
    )
    session.commit()

    result = FinancialIndicatorRepository(session).list_by_company(
        company.id,
        period_type=ReportingPeriodType.ANNUAL,
        indicator_codes=["roe"],
    )

    assert [item.indicator_code for item in result] == ["roe"]


def test_import_job_lookup_uses_idempotency_key(
    session: Session,
    master_data: tuple[Company, DataSource, Security],
):
    _, source, _ = master_data
    job = ImportJob(
        data_source_id=source.id,
        idempotency_key="csv_demo:market_price:600036:2026-01",
        job_type=ImportJobType.MARKET_PRICE,
        status=ImportJobStatus.PENDING,
    )
    session.add(job)
    session.commit()

    repository = ImportJobRepository(session)

    assert repository.get_by_idempotency_key(job.idempotency_key).id == job.id
    assert repository.list_by_status(ImportJobStatus.PENDING) == [job]
