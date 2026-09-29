"""Day15 Step2: local account login and signed identity resolution."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models.user_account import UserAccount
from finsight.main import app
from finsight.services.identity import (
    AuthenticationService,
    DuplicateAccount,
    IdentityService,
    InvalidCredentials,
    TokenCodec,
)

SECRET = "test-only-signing-secret-at-least-32-bytes"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def identity_environment():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    service = IdentityService(factory)
    try:
        yield factory, service, AuthenticationService(service, TokenCodec(SECRET))
    finally:
        engine.dispose()


def test_provision_stores_hash_and_normalizes_email(identity_environment) -> None:
    factory, identity, auth = identity_environment
    user_id = identity.provision("  Person@Example.COM  ", PASSWORD)
    with factory() as session:
        account = session.scalar(select(UserAccount).where(UserAccount.id == user_id))
        assert account is not None
        assert account.email == "person@example.com"
        assert account.password_hash.startswith("$argon2id$")
        assert PASSWORD not in account.password_hash
    assert auth.resolve(auth.login("PERSON@example.com", PASSWORD)).user_id == user_id
    with pytest.raises(DuplicateAccount):
        identity.provision("person@example.com", PASSWORD)


def test_invalid_credentials_expiry_and_account_deactivation(identity_environment) -> None:
    factory, identity, auth = identity_environment
    user_id = identity.provision("person@example.com", PASSWORD)
    with pytest.raises(InvalidCredentials):
        auth.login("person@example.com", "wrong password")
    with pytest.raises(InvalidCredentials):
        auth.login("unknown@example.com", PASSWORD)
    token = auth.login("person@example.com", PASSWORD)
    with pytest.raises(InvalidCredentials):
        auth.resolve(token + "tampered")
    old_token = auth.tokens.issue(user_id, now=datetime.now(UTC) - timedelta(hours=2))
    with pytest.raises(InvalidCredentials):
        auth.resolve(old_token)
    wrong_audience = jwt.encode(
        {
            "sub": str(user_id), "iss": "finsight", "aud": "different-api",
            "iat": datetime.now(UTC), "nbf": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5), "jti": "test",
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidCredentials):
        auth.resolve(wrong_audience)
    with factory() as session:
        account = session.get(UserAccount, user_id)
        assert account is not None
        account.is_active = False
        session.commit()
    with pytest.raises(InvalidCredentials):
        auth.resolve(token)


def test_login_and_me_are_disabled_without_secret() -> None:
    client = TestClient(app)
    assert client.post(
        "/api/v1/auth/login", json={"email": "person@example.com", "password": PASSWORD}
    ).status_code == 503
    assert client.get("/api/v1/auth/me").status_code == 503


def test_login_and_me_resolve_server_side_identity(identity_environment) -> None:
    _, identity, auth = identity_environment
    user_id = identity.provision("person@example.com", PASSWORD)
    app.state.auth_service = auth
    try:
        client = TestClient(app)
        invalid = client.post(
            "/api/v1/auth/login",
            json={"email": "person@example.com", "password": "wrong password"},
        )
        assert invalid.status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "person@example.com", "password": PASSWORD},
        )
        assert login.status_code == 200
        assert login.json()["expires_in_seconds"] == 1800
        token = login.json()["access_token"]
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["user_id"] == str(user_id)
        assert response.json()["memberships"] == []
        assert client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}
        ).status_code == 401
    finally:
        del app.state.auth_service


def test_weak_signing_secret_and_bad_password_are_rejected(identity_environment) -> None:
    _, identity, _ = identity_environment
    with pytest.raises(ValueError, match="at least 32 bytes"):
        TokenCodec("short")
    with pytest.raises(ValueError, match="12 to 1024"):
        identity.provision("person@example.com", "short")
