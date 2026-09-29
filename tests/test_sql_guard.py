import pytest

from finsight.security.sql_guard import SQLGuardError, validate_read_only_sql


def test_select_is_allowed_and_limit_is_added():
    safe_sql = validate_read_only_sql("SELECT symbol, close FROM market_prices")
    assert "SELECT" in safe_sql
    assert "LIMIT 500" in safe_sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM market_prices",
        "UPDATE market_prices SET close = 0",
        "DROP TABLE market_prices",
        "INSERT INTO market_prices(symbol, close) VALUES ('X', 1)",
    ],
)
def test_write_sql_is_rejected(sql):
    with pytest.raises(SQLGuardError):
        validate_read_only_sql(sql)


def test_empty_statement_is_rejected():
    with pytest.raises(SQLGuardError):
        validate_read_only_sql(";")
