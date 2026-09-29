"""Public market data means authenticated platform access, not anonymous HTTP access."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.api.routes.risk_report import get_market_price_reader
from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models.user_account import UserAccount
from finsight.main import app
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.market_price_reader import LoadedPriceSeries
from finsight.services.operation_audit import audit_target


def test_public_risk_requires_current_identity_before_loading_prices() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    identity = IdentityService(sessions)
    user_id = identity.provision("public-market@example.com", "test-password-long-enough")
    codec = TokenCodec("test-only-public-market-secret-at-least-32-bytes")
    token = codec.issue(user_id)
    prices = PriceSeries("PUBLIC", "none", "fixture", 1, tuple(
        PricePoint(date(2024, 1, 1) + timedelta(days=index), Decimal(100 + index))
        for index in range(21)
    ))

    class ReaderSpy:
        calls = 0

        def load(self, selection):
            self.calls += 1
            return LoadedPriceSeries(prices, "CNY")

    spy = ReaderSpy()
    selection = {
        "exchange": "SSE", "ticker": "PUBLIC", "source_code": "fixture",
        "adjustment_type": "none", "data_version": 1,
        "start_date": "2024-01-01", "end_date": "2024-01-21",
    }
    series = {
        "ticker": "PUBLIC", "adjustment_type": "none", "data_source": "fixture",
        "data_version": 1,
        "points": [{"trade_date": p.trade_date.isoformat(), "close_price": str(p.close_price)}
                   for p in prices.points],
    }
    payloads = {
        "analyze": {"prices": [100, 101, 102]},
        "asset-report": {"asset": series},
        "portfolio-report": {"positions": [{"prices": series, "weight": 1}]},
        "asset-report/from-db": {"asset": selection},
        "portfolio-report/from-db": {"positions": [{"selection": selection, "weight": 1}]},
    }
    previous = getattr(app.state, "auth_service", None)
    app.state.auth_service = AuthenticationService(identity, codec)
    app.dependency_overrides[get_market_price_reader] = lambda: spy
    try:
        client = TestClient(app)
        expired = codec.issue(user_id, now=datetime.now(UTC) - timedelta(hours=2))
        for suffix, payload in payloads.items():
            path = f"/api/v1/risk/{suffix}"
            for invalid in (None, "forged-token", expired):
                headers = {"Authorization": f"Bearer {invalid}"} if invalid else {}
                assert client.post(path, json=payload, headers=headers).status_code == 401
            assert audit_target("POST", path) is not None
        assert spy.calls == 0

        # No workspace membership is needed for this public-data capability.
        headers = {"Authorization": f"Bearer {token}"}
        for suffix, payload in payloads.items():
            assert client.post(f"/api/v1/risk/{suffix}", json=payload, headers=headers).status_code == 200
        assert spy.calls == 2
        with sessions() as session, session.begin():
            session.get(UserAccount, user_id).is_active = False
        for suffix, payload in payloads.items():
            assert client.post(f"/api/v1/risk/{suffix}", json=payload, headers=headers).status_code == 401
        assert spy.calls == 2
    finally:
        app.dependency_overrides.pop(get_market_price_reader, None)
        if previous is None:
            del app.state.auth_service
        else:
            app.state.auth_service = previous
        engine.dispose()
