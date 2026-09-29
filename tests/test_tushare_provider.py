import json
from datetime import date
from decimal import Decimal

import pytest

from finsight.domain.financial_data import FinancialQuery, MarketPriceQuery
from finsight.infrastructure.providers.tushare_provider import (
    TushareDataError,
    TushareFinancialDataProvider,
    TushareHttpClient,
    TusharePermissionError,
)
from finsight.services.financial_data_provider import FinancialDataProvider


def test_provider_maps_five_endpoints_without_network():
    calls = []
    responses = {
        "stock_company": [
            {"ts_code": "600036.SH", "com_name": "演示公司全称", "com_id": "", "setup_date": "19870408"}
        ],
        "stock_basic": [
            {"ts_code": "600036.SH", "name": "演示股票", "list_date": "20020409", "list_status": "L"}
        ],
        "daily": [
            {"ts_code": "600036.SH", "trade_date": "20250102", "open": 10, "high": 11,
             "low": 9, "close": 10.5, "vol": 2, "amount": 3}
        ],
        "income": [
            {"ts_code": "600036.SH", "ann_date": "20250401", "end_date": "20241231",
             "report_type": "1", "revenue": 100, "total_revenue": 120,
             "n_income_attr_p": 20},
            {"ts_code": "600036.SH", "ann_date": "20250401", "end_date": "20250331",
             "report_type": "1", "revenue": 30},
        ],
        "fina_indicator": [
            {"ts_code": "600036.SH", "ann_date": "20250401", "end_date": "20241231",
             "roe": 12.5, "debt_to_assets": 91.3}
        ],
    }

    def fake_api(name, params, fields):
        calls.append((name, params, fields))
        return responses[name]

    provider = TushareFinancialDataProvider(fake_api)
    assert isinstance(provider, FinancialDataProvider)
    assert provider.fetch_companies(["600036.SH"])[0].legal_name == "演示公司全称"
    assert provider.fetch_securities(["600036.SH"])[0].exchange == "SSE"
    prices = provider.fetch_market_prices(
        MarketPriceQuery(symbols=("600036.SH",), start_date=date(2025, 1, 1),
                         end_date=date(2025, 1, 31))
    )
    assert prices[0].volume == Decimal(200)  # 手 -> 股
    assert prices[0].amount == Decimal(3000)  # 千元 -> 元
    assert prices[0].adjustment_type == "none"
    query = FinancialQuery(company_codes=("600036.SH",), start_date=date(2024, 1, 1),
                           end_date=date(2025, 12, 31))
    statements = provider.fetch_financial_statements(query)
    assert {record.item_code for record in statements} == {
        "revenue", "total_revenue", "n_income_attr_p"
    }
    assert all(record.report_date == date(2024, 12, 31) for record in statements)
    indicators = provider.fetch_financial_indicators(query)
    assert [(record.indicator_code, record.value, record.unit) for record in indicators] == [
        ("roe", Decimal("12.5"), "%"),
        ("debt_to_assets", Decimal("91.3"), "%"),
    ]
    assert [call[0] for call in calls] == [
        "stock_company", "stock_basic", "daily", "income", "fina_indicator"
    ]


def test_provider_rejects_adjusted_price_request():
    provider = TushareFinancialDataProvider(lambda *_: [])
    with pytest.raises(TushareDataError, match="unadjusted"):
        provider.fetch_market_prices(
            MarketPriceQuery(symbols=("600036.SH",), start_date=date(2025, 1, 1),
                             end_date=date(2025, 1, 31), adjustment_type="qfq")
        )


def test_http_client_parses_table_and_hides_token_on_permission_error(monkeypatch):
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(self.body).encode("utf-8")

    captured = []

    def fake_urlopen(request, timeout):
        captured.append((json.loads(request.data), timeout))
        return Response({"code": 0, "data": {"fields": ["ts_code"], "items": [["600036.SH"]]}})

    monkeypatch.setattr("finsight.infrastructure.providers.tushare_provider.urlopen", fake_urlopen)
    client = TushareHttpClient("secret-test-token", timeout=5)
    assert client.query("stock_basic", {"ts_code": "600036.SH"}, "ts_code") == [
        {"ts_code": "600036.SH"}
    ]
    assert captured[0][0]["token"] == "secret-test-token"
    assert captured[0][1] == 5

    def denied_urlopen(request, timeout):
        return Response({"code": 2002, "msg": "permission denied"})

    monkeypatch.setattr("finsight.infrastructure.providers.tushare_provider.urlopen", denied_urlopen)
    with pytest.raises(TusharePermissionError, match="stock_basic") as error:
        client.query("stock_basic", {}, "ts_code")
    assert "secret-test-token" not in str(error.value)
