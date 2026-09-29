from datetime import date

from finsight.domain.financial_data import CompanyRecord, SecurityRecord
from finsight.services.data_freshness import assess_batch_freshness
from finsight.services.data_quality import FinancialDataBatch


def test_freshness_uses_observation_date_not_fetch_time():
    batch = FinancialDataBatch(
        companies=(CompanyRecord(source_code="csv_demo", company_code="CMB", legal_name="演示"),),
        securities=(SecurityRecord(
            source_code="csv_demo", company_code="CMB", exchange="SSE",
            ticker="600036", name="演示",
        ),),
    )
    report = assess_batch_freshness(batch, as_of=date(2025, 1, 10))
    assert report.has_stale_or_missing
    assert [(item.category, item.status) for item in report.items] == [
        ("market_price", "missing"), ("annual_financial", "missing")
    ]


def test_freshness_marks_old_and_future_observations():
    from decimal import Decimal

    from finsight.domain.financial_data import FinancialIndicatorRecord, MarketPriceRecord

    batch = FinancialDataBatch(
        companies=(CompanyRecord(source_code="csv_demo", company_code="CMB", legal_name="演示"),),
        securities=(SecurityRecord(
            source_code="csv_demo", company_code="CMB", exchange="SSE",
            ticker="600036", name="演示",
        ),),
        market_prices=(MarketPriceRecord(
            source_code="csv_demo", exchange="SSE", ticker="600036",
            trade_date=date(2025, 1, 2), open_price=Decimal(10), high_price=Decimal(11),
            low_price=Decimal(9), close_price=Decimal(10), volume=Decimal(100),
        ),),
        financial_indicators=(FinancialIndicatorRecord(
            source_code="csv_demo", company_code="CMB", report_date=date(2025, 12, 31),
            period_type="annual", indicator_code="roe", indicator_name="演示ROE",
            value=Decimal(12), unit="%",
        ),),
    )
    report = assess_batch_freshness(batch, as_of=date(2025, 1, 10))
    assert [item.status for item in report.items] == ["stale", "future"]


def test_market_only_batch_is_still_assessed():
    from decimal import Decimal

    from finsight.domain.financial_data import MarketPriceRecord

    batch = FinancialDataBatch(market_prices=(MarketPriceRecord(
        source_code="csv_demo", exchange="SSE", ticker="600036",
        trade_date=date(2025, 1, 2), open_price=Decimal(10), high_price=Decimal(11),
        low_price=Decimal(9), close_price=Decimal(10), volume=Decimal(100),
    ),))
    report = assess_batch_freshness(batch, as_of=date(2025, 1, 10))
    assert [(item.key, item.status) for item in report.items] == [
        ("SSE/600036", "stale")
    ]
