from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialQuery,
    FinancialStatementRecord,
    MarketPriceQuery,
    MarketPriceRecord,
    SecurityRecord,
)


@runtime_checkable
class FinancialDataProvider(Protocol):
    """Source-neutral contract implemented by external financial data adapters."""

    @property
    def source_code(self) -> str: ...

    def fetch_companies(self, company_codes: Sequence[str]) -> list[CompanyRecord]: ...

    def fetch_securities(self, company_codes: Sequence[str]) -> list[SecurityRecord]: ...

    def fetch_market_prices(self, query: MarketPriceQuery) -> list[MarketPriceRecord]: ...

    def fetch_financial_statements(
        self,
        query: FinancialQuery,
    ) -> list[FinancialStatementRecord]: ...

    def fetch_financial_indicators(
        self,
        query: FinancialQuery,
    ) -> list[FinancialIndicatorRecord]: ...
