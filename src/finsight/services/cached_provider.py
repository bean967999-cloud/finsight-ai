"""Short-lived, bounded cache around any financial data provider."""

from collections.abc import Callable, Sequence
from time import monotonic
from typing import TypeVar, cast

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialQuery,
    FinancialRecord,
    FinancialStatementRecord,
    MarketPriceQuery,
    MarketPriceRecord,
    SecurityRecord,
)
from finsight.services.financial_data_provider import FinancialDataProvider

RecordT = TypeVar("RecordT", bound=FinancialRecord)


class CachedFinancialDataProvider:
    """Cache successful results only; stale entries and errors are never returned."""

    def __init__(
        self,
        provider: FinancialDataProvider,
        *,
        ttl_seconds: float = 300,
        max_entries: int = 128,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("ttl_seconds and max_entries must be positive")
        self.provider = provider
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries: dict[tuple[str, str], tuple[float, tuple[FinancialRecord, ...]]] = {}

    @property
    def source_code(self) -> str:
        return self.provider.source_code

    def clear(self) -> None:
        self._entries.clear()

    def _cached(
        self, category: str, key: str, loader: Callable[[], list[RecordT]]
    ) -> list[RecordT]:
        cache_key = (category, key)
        now = self.clock()
        entry = self._entries.get(cache_key)
        if entry is not None and now < entry[0]:
            return list(cast("tuple[RecordT, ...]", entry[1]))
        self._entries.pop(cache_key, None)
        result = loader()  # Exceptions are not cached and do not reuse an expired entry.
        if len(self._entries) >= self.max_entries:
            self._entries.pop(next(iter(self._entries)))
        self._entries[cache_key] = (now + self.ttl_seconds, tuple(result))
        return list(result)

    def fetch_companies(self, company_codes: Sequence[str]) -> list[CompanyRecord]:
        codes = tuple(company_codes)
        return self._cached("companies", repr(codes), lambda: self.provider.fetch_companies(codes))

    def fetch_securities(self, company_codes: Sequence[str]) -> list[SecurityRecord]:
        codes = tuple(company_codes)
        return self._cached("securities", repr(codes), lambda: self.provider.fetch_securities(codes))

    def fetch_market_prices(self, query: MarketPriceQuery) -> list[MarketPriceRecord]:
        return self._cached(
            "market_prices", query.model_dump_json(),
            lambda: self.provider.fetch_market_prices(query),
        )

    def fetch_financial_statements(
        self, query: FinancialQuery
    ) -> list[FinancialStatementRecord]:
        return self._cached(
            "financial_statements", query.model_dump_json(),
            lambda: self.provider.fetch_financial_statements(query),
        )

    def fetch_financial_indicators(
        self, query: FinancialQuery
    ) -> list[FinancialIndicatorRecord]:
        return self._cached(
            "financial_indicators", query.model_dump_json(),
            lambda: self.provider.fetch_financial_indicators(query),
        )
