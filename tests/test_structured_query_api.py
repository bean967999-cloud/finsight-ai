from decimal import Decimal

from fastapi.testclient import TestClient

from finsight.api.routes.structured_query import get_structured_query
from finsight.domain.query_execution import QueryExecutionResult
from finsight.main import app
from finsight.services.structured_query import StructuredQueryService


class FakeExecutor:
    def execute(self, guarded):
        columns = guarded.compiled.selected_columns
        row = {column: None for column in columns}
        row.update({"company_code": "CMB", "item_code": "revenue", "value": Decimal(100)})
        return QueryExecutionResult(
            query_sha256=guarded.compiled.query_sha256,
            sql_sha256="b" * 64, columns=columns, rows=(row,),
            row_count=1, execution_ms=3.25,
        )


def payload():
    return {
        "query": "查询 CMB 2024 年营业收入",
        "intent": "financial_statement",
        "entities": {"company_codes": ["CMB"]},
        "metrics": [{"term": "营业收入"}],
        "time": {"report_years": [2024]},
        "period_type": "annual",
        "statement_type": "income_statement",
        "limit": 10,
    }


def test_api_returns_traceable_query_without_echoing_raw_question() -> None:
    app.dependency_overrides[get_structured_query] = lambda: StructuredQueryService(FakeExecutor())
    try:
        response = TestClient(app).post("/api/v1/query/structured", json=payload())
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["query_sha256"] and "query" not in body["plan"]
    assert body["resolved_metrics"][0]["code"] == "revenue"
    assert body["parameters"]["company_code_0"] == "CMB"
    assert body["rows"][0]["value"] == "100"
    assert body["data_period"]["report_years"] == [2024]
    assert payload()["query"] not in response.text


def test_api_rejects_missing_scope_and_unknown_metric() -> None:
    app.dependency_overrides[get_structured_query] = lambda: StructuredQueryService(FakeExecutor())
    try:
        missing_scope = payload()
        missing_scope["time"] = {}
        first = TestClient(app).post("/api/v1/query/structured", json=missing_scope)
        unknown = payload()
        unknown["metrics"] = [{"term": "未知指标"}]
        second = TestClient(app).post("/api/v1/query/structured", json=unknown)
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == 422
    assert second.status_code == 422
