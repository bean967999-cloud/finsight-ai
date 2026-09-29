from unittest.mock import Mock

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import finsight.infrastructure.database.session as session_module
from finsight.infrastructure.database import Base, SessionFactory, engine, get_db_session


def test_database_engine_uses_postgresql_psycopg():
    assert isinstance(engine, Engine)
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.pool._pre_ping is True


def test_session_factory_uses_shared_engine():
    session = SessionFactory()
    try:
        assert isinstance(session, Session)
        assert session.bind is engine
        assert session.autoflush is False
        assert session.expire_on_commit is False
    finally:
        session.close()


def test_fastapi_session_dependency_closes_session(monkeypatch):
    fake_session = Mock(spec=Session)
    monkeypatch.setattr(session_module, "SessionFactory", Mock(return_value=fake_session))

    dependency = get_db_session()
    session = next(dependency)

    assert session is fake_session
    dependency.close()
    fake_session.close.assert_called_once_with()


def test_session_scope_commits_and_closes(monkeypatch):
    fake_session = Mock(spec=Session)
    monkeypatch.setattr(session_module, "SessionFactory", Mock(return_value=fake_session))

    with session_module.session_scope() as session:
        assert session is fake_session

    fake_session.commit.assert_called_once_with()
    fake_session.rollback.assert_not_called()
    fake_session.close.assert_called_once_with()


def test_session_scope_rolls_back_and_closes(monkeypatch):
    fake_session = Mock(spec=Session)
    monkeypatch.setattr(session_module, "SessionFactory", Mock(return_value=fake_session))

    with pytest.raises(RuntimeError, match="failed"), session_module.session_scope():
        raise RuntimeError("failed")

    fake_session.commit.assert_not_called()
    fake_session.rollback.assert_called_once_with()
    fake_session.close.assert_called_once_with()


def test_declarative_base_has_stable_constraint_naming():
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
    assert Base.metadata.naming_convention["fk"].startswith("fk_%(table_name)s")
