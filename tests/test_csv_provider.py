from datetime import date

import pytest

from finsight.domain.financial_data import FinancialQuery, MarketPriceQuery
from finsight.infrastructure.providers.csv_provider import (
    CsvDataError,
    CsvFinancialDataProvider,
)
from finsight.services.financial_data_provider import FinancialDataProvider


@pytest.fixture
def csv_directory(tmp_path):
    samples = {
        "companies": (
            "company_code,legal_name,short_name\n"
            "CMB,演示招商银行股份有限公司,演示招行\n"
            "PAB,演示平安银行股份有限公司,演示平安\n"
        ),
        "securities": (
            "company_code,exchange,ticker,name\n"
            "CMB,SSE,600036,演示证券甲\n"
            "PAB,SZSE,000001,演示证券乙\n"
        ),
        "market_prices": (
            "exchange,ticker,trade_date,open_price,high_price,low_price,"
            "close_price,volume,amount,adjustment_type\n"
            "SSE,600036,2025-01-02,10,11,9,10.5,100,1000,none\n"
            "SSE,600036,2025-01-03,11,12,10,11.5,120,1200,none\n"
            "SZSE,000001,2025-01-02,8,9,7,8.5,90,900,none\n"
        ),
        "financial_statements": (
            "company_code,report_date,period_type,statement_type,item_code,"
            "item_name,value\n"
            "CMB,2024-12-31,annual,income_statement,revenue,演示营业收入,1000\n"
            "CMB,2025-03-31,quarterly,income_statement,revenue,演示营业收入,250\n"
        ),
        "financial_indicators": (
            "company_code,report_date,period_type,indicator_code,indicator_name,"
            "value,unit\n"
            "CMB,2024-12-31,annual,roe,演示净资产收益率,12.5,%\n"
            "PAB,2024-12-31,annual,roe,演示净资产收益率,11.2,%\n"
        ),
    }
    for name, content in samples.items():
        (tmp_path / f"{name}.csv").write_text(content, encoding="utf-8")
    return tmp_path


def test_csv_provider_implements_contract_and_filters_all_five_types(csv_directory):
    provider = CsvFinancialDataProvider(csv_directory)
    assert isinstance(provider, FinancialDataProvider)
    assert provider.source_code == "csv_demo"

    companies = provider.fetch_companies(["CMB"])
    securities = provider.fetch_securities(["PAB"])
    prices = provider.fetch_market_prices(
        MarketPriceQuery(
            symbols=("600036.SH",),
            start_date=date(2025, 1, 3),
            end_date=date(2025, 1, 3),
        )
    )
    financial_query = FinancialQuery(
        company_codes=("CMB",),
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
    )
    statements = provider.fetch_financial_statements(financial_query)
    indicators = provider.fetch_financial_indicators(financial_query)

    assert [record.company_code for record in companies] == ["CMB"]
    assert [record.ticker for record in securities] == ["000001"]
    assert [record.trade_date for record in prices] == [date(2025, 1, 3)]
    assert [record.value for record in statements] == [1000]
    assert [record.value for record in indicators] == [12.5]
    assert all(record.source_code == "csv_demo" for record in companies + securities + prices)
    assert prices[0].source_record_id == "market_prices:3"
    assert provider.fetch_market_prices(
        MarketPriceQuery(
            symbols=("000001.SZ",),
            start_date=date(2025, 1, 3),
            end_date=date(2025, 1, 3),
        )
    ) == []


def test_csv_provider_rejects_missing_file_and_columns(csv_directory):
    provider = CsvFinancialDataProvider(csv_directory)
    (csv_directory / "companies.csv").unlink()
    with pytest.raises(CsvDataError, match="Missing CSV file"):
        provider.fetch_companies(["CMB"])

    (csv_directory / "companies.csv").write_text("company_code\nCMB\n", encoding="utf-8")
    with pytest.raises(CsvDataError, match="Missing columns.*legal_name"):
        provider.fetch_companies(["CMB"])


@pytest.mark.parametrize(
    "bad_row, message",
    [
        ("SSE,600036,not-a-date,10,11,9,10.5,100,1000,none", "line 2"),
        ("SSE,600036,2025-01-02,10,9,8,10.5,100,1000,none", "line 2"),
    ],
)
def test_csv_provider_reports_invalid_row_with_location(csv_directory, bad_row, message):
    path = csv_directory / "market_prices.csv"
    header = path.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(f"{header}\n{bad_row}\n", encoding="utf-8")
    provider = CsvFinancialDataProvider(csv_directory)

    with pytest.raises(CsvDataError, match=message):
        provider.fetch_market_prices(
            MarketPriceQuery(
                symbols=("600036.SH",),
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
            )
        )
