"""Opt-in real PostgreSQL acceptance for database-backed risk reports."""

import os
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

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
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 to run against local PostgreSQL",
)


def _market_record(ticker: str, day: date, value: str, index: int) -> MarketPriceRecord:
    close = Decimal(value)
    return MarketPriceRecord(
        source_code="risk_fixture",
        source_record_id=f"risk:{ticker}:{index}",
        exchange="SSE",
        ticker=ticker,
        trade_date=day,
        open_price=close,
        high_price=close,
        low_price=close,
        close_price=close,
        volume=Decimal(100),
    )


def _selection(ticker: str, start: date, end: date) -> dict[str, object]:
    return {
        "exchange": "SSE",
        "ticker": ticker,
        "source_code": "risk_fixture",
        "adjustment_type": "none",
        "data_version": 1,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def test_real_postgres_import_read_and_http_risk_reports(agent_auth) -> None:
    database_url = get_settings().database_url
    schema = f"finsight_risk_{uuid4().hex[:12]}"
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

        dates: list[date] = []
        current = date(2025, 1, 2)
        while len(dates) < 21:
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)
        asset_prices = ["100", "110", "99", *(str(100 + index) for index in range(18))]
        benchmark_prices = ["100", "105", "100", *(str(101 + index) for index in range(18))]
        rows = tuple(
            _market_record(ticker, day, value, index)
            for ticker, values in (("999991", asset_prices), ("999992", benchmark_prices))
            for index, (day, value) in enumerate(zip(dates, values, strict=True))
        )
        origin = {"source_code": "risk_fixture", "source_record_id": "risk:base"}
        FinancialImportService(sessions).import_batch(
            FinancialDataBatch(
                companies=(CompanyRecord(
                    **origin, company_code="RISK_DEMO", legal_name="风险验收公司",
                ),),
                securities=(
                    SecurityRecord(
                        **origin, company_code="RISK_DEMO", exchange="SSE",
                        ticker="999991", name="风险验收资产",
                    ),
                    SecurityRecord(
                        **{**origin, "source_record_id": "risk:index"},
                        company_code="RISK_DEMO", exchange="SSE",
                        ticker="999992", name="风险验收基准",
                    ),
                ),
                market_prices=rows,
            ),
            source_code="risk_fixture",
            idempotency_key="risk-fixture",
        )
        app.dependency_overrides[get_market_price_reader] = lambda: MarketPriceReader(sessions)
        client = TestClient(app, headers=agent_auth.headers())
        asset = _selection("999991", dates[0], dates[-1])
        benchmark = _selection("999992", dates[0], dates[-1])

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
        missing = client.post(
            "/api/v1/risk/asset-report/from-db",
            json={"asset": {**asset, "source_code": "wrong_source"}},
        )
        too_short = client.post(
            "/api/v1/risk/asset-report/from-db",
            json={"asset": {**asset, "end_date": dates[2].isoformat()}},
        )

        assert single.status_code == 200
        assert portfolio.status_code == 200
        assert missing.status_code == 404
        assert too_short.status_code == 422
        single_body = single.json()
        assert single_body["price_observations"] == 21
        assert single_body["data_source"] == "risk_fixture"
        assert single_body["start_date"] == dates[0].isoformat()
        assert single_body["end_date"] == dates[-1].isoformat()
        assert single_body["drawdown"]["max_drawdown"] == pytest.approx(-0.1)
        assert single_body["tail_risk"]["observations"] == 20
        assert single_body["tail_risk"]["tail_observations"] == 1
        assert single_body["beta"]["aligned_observations"] == 20
        assert not any("supplied by the caller" in note for note in single_body["warnings"])
        portfolio_body = portfolio.json()
        assert portfolio_body["portfolio"]["aligned_observations"] == 20
        assert portfolio_body["portfolio"]["tickers"] == ["999991", "999992"]
        assert portfolio_body["sources"] == [
            ["999991", "risk_fixture", 1], ["999992", "risk_fixture", 1]
        ]
        assert portfolio_body["portfolio"]["annualized_volatility"] >= 0
        assert not any("supplied by the caller" in note for note in portfolio_body["warnings"])
    finally:
        app.dependency_overrides.clear()
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
