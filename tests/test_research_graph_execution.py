"""Day13 Step4: graph routing, parallel independent calls and bounded retry."""

from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from finsight.agents.graph import build_research_graph
from finsight.agents.tools import ResearchToolAdapter
from finsight.domain.query_plan import PlanStatus, QueryIntent
from finsight.domain.research_flow import ResearchTool, ToolStatus
from finsight.main import app
from finsight.services.query_planning import build_query_plan


class ParallelDocument:
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier
        self.calls = 0

    def search(self, query: str, *, criteria=None):
        self.calls += 1
        self.barrier.wait(timeout=2)
        return object()


class ParallelStructured:
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier
        self.calls = 0

    def execute(self, plan):
        self.calls += 1
        self.barrier.wait(timeout=2)
        return object()


class FlakyDocument:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.calls = 0
        self.always_fail = always_fail

    def search(self, query: str, *, criteria=None):
        self.calls += 1
        if self.always_fail or self.calls == 1:
            raise ConnectionError("temporary outage")
        return object()


def test_mixed_plan_runs_independent_services_in_parallel_and_preserves_order() -> None:
    barrier = Barrier(2)
    document = ParallelDocument(barrier)
    structured = ParallelStructured(barrier)
    query = "比较年报收入与财务数据"
    plan = build_query_plan(query, status=PlanStatus.READY, intent=QueryIntent.COMPANY_LOOKUP)
    graph = build_research_graph(
        ResearchToolAdapter(document_search=document, structured_query=structured)
    )
    result = graph.invoke({"query": query, "structured_plan": plan, "knowledge_base_id": str(uuid4())})
    assert document.calls == structured.calls == 1
    assert tuple(item.tool for item in result["tool_results"]) == (
        ResearchTool.DOCUMENT_SEARCH,
        ResearchTool.STRUCTURED_QUERY,
    )
    assert all(item.status == ToolStatus.SUCCEEDED for item in result["tool_results"])
    assert all(item.evidence == () for item in result["tool_results"])
    assert "risk_metrics" not in result


def test_transient_document_failure_retries_once_only() -> None:
    document = FlakyDocument()
    graph = build_research_graph(ResearchToolAdapter(document_search=document))
    result = graph.invoke({"query": "查看年报原文", "knowledge_base_id": str(uuid4())})
    assert document.calls == 2
    assert result["tool_results"][0].status == ToolStatus.SUCCEEDED

    always_down = FlakyDocument(always_fail=True)
    graph = build_research_graph(ResearchToolAdapter(document_search=always_down))
    result = graph.invoke({"query": "查看年报原文", "knowledge_base_id": str(uuid4())})
    assert always_down.calls == 2
    assert result["tool_results"][0].status == ToolStatus.UNAVAILABLE
    assert result["tool_results"][0].error_code == "DocumentSearchUnavailable"


def test_missing_prerequisite_does_not_retry_or_invent_metrics() -> None:
    result = build_research_graph().invoke({"query": "计算组合波动率"})
    assert result["tool_results"][0].error_code == "PricesRequired"
    assert "risk_metrics" not in result
    assert "plan_limitations" in result


def test_unsupported_question_skips_tool_node() -> None:
    result = build_research_graph().invoke({"query": "推荐附近餐厅"})
    assert result["classified_intent"] == "unsupported"
    assert "tool_results" not in result


def test_http_risk_path_uses_tool_execution_and_keeps_response_compatible(agent_auth) -> None:
    response = TestClient(app).post(
        "/api/v1/agent/query",
        headers=agent_auth.headers(),
        json={"query": "计算价格波动率", "prices": [100, 102, 101, 105], "workspace_id": str(agent_auth.workspace_id)},
    )
    assert response.status_code == 200
    assert response.json()["intent"] == "risk_analysis"
    assert response.json()["risk_metrics"]["observations"] == 4
