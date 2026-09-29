from datetime import date
from decimal import Decimal

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialStatementRecord,
    MarketPriceRecord,
    SecurityRecord,
)
from finsight.services.data_quality import FinancialDataBatch, validate_financial_batch


def make_batch() -> FinancialDataBatch:
    lineage = {"source_code": "csv_demo", "source_record_id": "demo:1"}
    return FinancialDataBatch(
        companies=(CompanyRecord(**lineage, company_code="CMB", legal_name="演示公司"),),
        securities=(
            SecurityRecord(
                **lineage, company_code="CMB", exchange="SSE", ticker="600036", name="演示股票"
            ),
        ),
        market_prices=(
            MarketPriceRecord(
                **lineage, exchange="SSE", ticker="600036", trade_date=date(2025, 1, 2),
                open_price=Decimal(10), high_price=Decimal(11), low_price=Decimal(9),
                close_price=Decimal(10), volume=Decimal(100),
            ),
        ),
        financial_statements=(
            FinancialStatementRecord(
                **lineage, company_code="CMB", report_date=date(2024, 12, 31),
                period_type="annual", statement_type="income_statement", item_code="revenue",
                item_name="演示营业收入", value=Decimal(100),
            ),
        ),
        financial_indicators=(
            FinancialIndicatorRecord(
                **lineage, company_code="CMB", report_date=date(2024, 12, 31),
                period_type="annual", indicator_code="roe", indicator_name="演示ROE",
                value=Decimal("12.5"), unit="%",
            ),
        ),
    )


def test_valid_batch_has_no_quality_issues():
    report = validate_financial_batch(make_batch(), "csv_demo")
    assert report.is_valid
    assert report.checked_rows == 5
    assert report.issues == ()


def test_quality_report_identifies_source_relationship_and_duplicate_errors():
    batch = make_batch()
    wrong_source = batch.market_prices[0].model_copy(update={"source_code": "tushare"})
    unknown_security = batch.securities[0].model_copy(update={"company_code": "UNKNOWN"})
    duplicate_indicator = batch.financial_indicators[0].model_copy()
    report = validate_financial_batch(
        FinancialDataBatch(
            companies=batch.companies,
            securities=(unknown_security,),
            market_prices=(wrong_source, wrong_source),
            financial_indicators=(batch.financial_indicators[0], duplicate_indicator),
        ),
        "csv_demo",
    )
    assert not report.is_valid
    assert report.error_count == 5
    assert {issue.collection for issue in report.issues} == {
        "securities", "market_prices", "financial_indicators"
    }


def test_missing_values_warn_but_do_not_become_zero():
    batch = make_batch()
    missing = batch.financial_statements[0].model_copy(
        update={"value": None, "source_record_id": None}
    )
    report = validate_financial_batch(
        FinancialDataBatch(financial_statements=(missing,)), "csv_demo"
    )
    assert report.is_valid
    assert report.warning_count == 2
    assert missing.value is None


def test_wrong_units_block_import():
    batch = make_batch()
    bad_statement = batch.financial_statements[0].model_copy(update={"unit": "thousand_yuan"})
    bad_indicator = batch.financial_indicators[0].model_copy(update={"unit": "ratio"})
    report = validate_financial_batch(
        FinancialDataBatch(
            financial_statements=(bad_statement,), financial_indicators=(bad_indicator,)
        ),
        "csv_demo",
    )
    assert report.error_count == 2
    assert not report.is_valid
