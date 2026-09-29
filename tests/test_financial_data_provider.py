from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialQuery,
    FinancialStatementRecord,
    MarketPriceQuery,
    MarketPriceRecord,
    SecurityRecord,
)
from finsight.services.financial_data_provider import FinancialDataProvider


class InMemoryFinancialDataProvider:
    @property
    def source_code(self) -> str:
        return "memory_test"

    def fetch_companies(self, company_codes: Sequence[str]) -> list[CompanyRecord]:
        return [
            CompanyRecord(
                source_code=self.source_code,
                company_code=code,
                legal_name=f"{code} Company",
            )
            for code in company_codes
        ]

    def fetch_securities(self, company_codes: Sequence[str]) -> list[SecurityRecord]:
        return []

    def fetch_market_prices(self, query: MarketPriceQuery) -> list[MarketPriceRecord]:
        return []

    def fetch_financial_statements(
        self,
        query: FinancialQuery,
    ) -> list[FinancialStatementRecord]:
        return []

    def fetch_financial_indicators(
        self,
        query: FinancialQuery,
    ) -> list[FinancialIndicatorRecord]:
        return []


def test_structural_provider_contract_accepts_an_independent_adapter():
    provider = InMemoryFinancialDataProvider()

    assert isinstance(provider, FinancialDataProvider)
    assert provider.fetch_companies(["CMB"])[0].source_code == "memory_test"


def test_normalized_records_are_immutable_and_keep_lineage():
    record = CompanyRecord(
        source_code="csv_demo",
        source_record_id="companies:1",
        data_version=2,
        company_code=" CMB ",
        legal_name=" 招商银行股份有限公司 ",
    )

    assert record.company_code == "CMB"
    assert record.legal_name == "招商银行股份有限公司"
    assert record.source_record_id == "companies:1"
    assert record.data_version == 2
    assert record.fetched_at.tzinfo is not None

    with pytest.raises(ValidationError):
        record.company_code = "CHANGED"


def test_market_price_contract_rejects_inconsistent_ohlc():
    with pytest.raises(ValidationError, match="high_price must cover"):
        MarketPriceRecord(
            source_code="csv_demo",
            exchange="SSE",
            ticker="600036",
            trade_date=date(2026, 1, 5),
            open_price=Decimal("10.00"),
            high_price=Decimal("10.50"),
            low_price=Decimal("9.80"),
            close_price=Decimal("10.80"),
            volume=Decimal(1000),
        )


def test_market_price_query_rejects_reversed_dates():
    with pytest.raises(ValidationError, match="start_date must not be after"):
        MarketPriceQuery(
            symbols=("600036.SH",),
            start_date=date(2026, 2, 1),
            end_date=date(2026, 1, 1),
        )


def test_financial_query_defaults_to_annual_reports():
    query = FinancialQuery(
        company_codes=("CMB", "PAB"),
        start_date=date(2023, 1, 1),
        end_date=date(2025, 12, 31),
    )

    assert [period.value for period in query.period_types] == ["annual"]
