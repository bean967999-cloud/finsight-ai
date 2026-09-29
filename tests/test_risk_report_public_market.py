"""Opt-in public-market-data to PostgreSQL to HTTP risk acceptance."""

import os
import time
from datetime import date
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.api.routes.risk_report import get_market_price_reader
from finsight.core.config import get_settings
from finsight.domain.financial_data import CompanyRecord, MarketPriceRecord, SecurityRecord
from finsight.infrastructure.database import Base
from finsight.main import app
from finsight.services.data_quality import FinancialDataBatch
from finsight.services.financial_import import FinancialImportService
from finsight.services.market_price_reader import MarketPriceReader

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_MARKET_INTEGRATION") != "1"
    or os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_MARKET_INTEGRATION=1 and FINSIGHT_PG_INTEGRATION=1",
)


def _fetch_public_daily_prices(ticker: str) -> tuple[MarketPriceRecord, ...]:
    request = {
        "secid": f"1.{ticker}",
        "klt": "101",
        "fqt": "0",
        "beg": "20250101",
        "end": "20250228",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
    }
    for attempt in range(3):
        try:
            response = httpx.get(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params=request,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=15,
            )
            break
        except httpx.TransportError:
            if attempt == 2:
                pytest.skip("public market endpoint did not return a response")
            time.sleep(attempt + 1)
    response.raise_for_status()
    data = response.json()["data"]
    if data is None or not data["klines"]:
        raise AssertionError(f"no public daily prices returned for {ticker}")

    records: list[MarketPriceRecord] = []
    for line in data["klines"]:
        trade_day, open_price, close_price, high_price, low_price, volume, amount, *_ = (
            line.split(",")
        )
        records.append(MarketPriceRecord(
            source_code="eastmoney_public",
            source_record_id=f"{ticker}:{trade_day}",
            exchange="SSE",
            ticker=ticker,
            trade_date=date.fromisoformat(trade_day),
            open_price=Decimal(open_price),
            high_price=Decimal(high_price),
            low_price=Decimal(low_price),
            close_price=Decimal(close_price),
            volume=Decimal(volume),
            amount=Decimal(amount),
            adjustment_type="none",
        ))
    return tuple(records)


def _selection(ticker: str, start: date, end: date) -> dict[str, object]:
    return {
        "exchange": "SSE",
        "ticker": ticker,
        "source_code": "eastmoney_public",
        "adjustment_type": "none",
        "data_version": 1,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def test_public_market_prices_reach_database_backed_risk_http_reports(agent_auth) -> None:
    first = _fetch_public_daily_prices("600519")
    second = _fetch_public_daily_prices("600036")
    assert len(first) >= 30 and len(second) >= 30
    assert [record.trade_date for record in first] == [record.trade_date for record in second]

    database_url = get_settings().database_url
    schema = f"finsight_public_risk_{uuid4().hex[:12]}"
    admin_engine = create_engine(database_url)
    test_engine = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        test_engine = create_engine(
            database_url, connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        origin = {"source_code": "eastmoney_public", "source_record_id": "public:base"}
        FinancialImportService(sessions).import_batch(
            FinancialDataBatch(
                companies=(
                    CompanyRecord(
                        **origin, company_code="PUBLIC_519", legal_name="公开行情验收主体一",
                    ),
                    CompanyRecord(
                        **{**origin, "source_record_id": "public:second"},
                        company_code="PUBLIC_036", legal_name="公开行情验收主体二",
                    ),
                ),
                securities=(
                    SecurityRecord(
                        **origin, company_code="PUBLIC_519", exchange="SSE",
                        ticker="600519", name="公开行情验收证券一",
                    ),
                    SecurityRecord(
                        **{**origin, "source_record_id": "public:second"},
                        company_code="PUBLIC_036", exchange="SSE",
                        ticker="600036", name="公开行情验收证券二",
                    ),
                ),
                market_prices=first + second,
            ),
            source_code="eastmoney_public",
            idempotency_key="public-market-risk-acceptance",
        )
        app.dependency_overrides[get_market_price_reader] = lambda: MarketPriceReader(sessions)
        client = TestClient(app, headers=agent_auth.headers())
        asset = _selection("600519", first[0].trade_date, first[-1].trade_date)
        benchmark = _selection("600036", second[0].trade_date, second[-1].trade_date)

        single = client.post(
            "/api/v1/risk/asset-report/from-db",
            json={"asset": asset, "benchmark": benchmark, "confidence": 0.95},
        )
        portfolio = client.post(
            "/api/v1/risk/portfolio-report/from-db",
            json={"positions": [
                {"selection": asset, "weight": 0.6},
                {"selection": benchmark, "weight": 0.4},
            ]},
        )
        assert single.status_code == 200, single.text
        assert portfolio.status_code == 200, portfolio.text
        body = single.json()
        assert body["price_observations"] == len(first)
        assert body["data_source"] == "eastmoney_public"
        assert body["adjustment_type"] == "none"
        assert body["beta"]["aligned_observations"] == len(first) - 1
        assert body["tail_risk"]["conditional_value_at_risk"] >= body["tail_risk"]["value_at_risk"]
        assert body["drawdown"]["max_drawdown"] <= 0
        portfolio_body = portfolio.json()["portfolio"]
        assert portfolio_body["aligned_observations"] == len(first) - 1
        assert portfolio_body["tickers"] == ["600519", "600036"]
        assert portfolio_body["annualized_volatility"] >= 0
        print(
            "public market acceptance:",
            f"rows_per_security={len(first)}",
            f"start={first[0].trade_date}",
            f"end={first[-1].trade_date}",
            f"max_drawdown={body['drawdown']['max_drawdown']:.6f}",
            f"var95={body['tail_risk']['value_at_risk']:.6f}",
            f"cvar95={body['tail_risk']['conditional_value_at_risk']:.6f}",
            f"beta={body['beta']['beta']:.6f}",
            f"portfolio_volatility={portfolio_body['annualized_volatility']:.6f}",
        )
    finally:
        app.dependency_overrides.clear()
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
