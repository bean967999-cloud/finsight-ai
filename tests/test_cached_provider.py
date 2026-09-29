import pytest

from finsight.domain.financial_data import CompanyRecord
from finsight.services.cached_provider import CachedFinancialDataProvider
from finsight.services.financial_data_provider import FinancialDataProvider


class FakeProvider:
    source_code = "csv_demo"

    def __init__(self):
        self.calls = 0
        self.fail = False

    def fetch_companies(self, codes):
        self.calls += 1
        if self.fail:
            raise RuntimeError("offline")
        return [CompanyRecord(source_code=self.source_code, company_code=c, legal_name="演示")
                for c in codes]

    def fetch_securities(self, codes):
        return []

    def fetch_market_prices(self, query):
        return []

    def fetch_financial_statements(self, query):
        return []

    def fetch_financial_indicators(self, query):
        return []


def test_cache_reuses_fresh_result_and_refetches_after_ttl():
    now = [0.0]
    provider = FakeProvider()
    cached = CachedFinancialDataProvider(provider, ttl_seconds=10, clock=lambda: now[0])
    assert isinstance(cached, FinancialDataProvider)
    first = cached.fetch_companies(["CMB"])
    first.clear()
    assert len(cached.fetch_companies(["CMB"])) == 1
    assert provider.calls == 1
    now[0] = 10.0
    cached.fetch_companies(["CMB"])
    assert provider.calls == 2


def test_expired_cache_does_not_hide_provider_error():
    now = [0.0]
    provider = FakeProvider()
    cached = CachedFinancialDataProvider(provider, ttl_seconds=5, clock=lambda: now[0])
    cached.fetch_companies(["CMB"])
    now[0] = 6.0
    provider.fail = True
    with pytest.raises(RuntimeError, match="offline"):
        cached.fetch_companies(["CMB"])
    provider.fail = False
    cached.fetch_companies(["CMB"])
    assert provider.calls == 3
