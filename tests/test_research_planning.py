"""Day13 Step2: deterministic intent and plan without executing new tools."""

import pytest
from fastapi.testclient import TestClient

from finsight.agents.graph import classify_intent, research_graph, route_after_classify
from finsight.agents.planning import plan_research
from finsight.domain.research_flow import ResearchIntent, ResearchQuestion, ResearchTool
from finsight.main import app


@pytest.mark.parametrize(
    ("query", "intent", "tools"),
    [
        ("查找年报原文页码", ResearchIntent.DOCUMENT, (ResearchTool.DOCUMENT_SEARCH,)),
        ("比较净利润同比", ResearchIntent.STRUCTURED, (ResearchTool.STRUCTURED_QUERY,)),
        ("计算组合VaR", ResearchIntent.RISK, (ResearchTool.RISK_CALCULATION,)),
        (
            "比较年报披露的营业收入与财务数据",
            ResearchIntent.MIXED,
            (ResearchTool.DOCUMENT_SEARCH, ResearchTool.STRUCTURED_QUERY),
        ),
        (
            "用财报原文解释组合回撤与净利润变化",
            ResearchIntent.MIXED,
            (
                ResearchTool.DOCUMENT_SEARCH,
                ResearchTool.STRUCTURED_QUERY,
                ResearchTool.RISK_CALCULATION,
            ),
        ),
        ("推荐附近餐厅", ResearchIntent.UNSUPPORTED, ()),
        ("what is a variant", ResearchIntent.UNSUPPORTED, ()),
    ],
)
def test_planner_selects_inspectable_tools(query, intent, tools) -> None:
    result = plan_research(ResearchQuestion(query=query))
    assert result.intent == intent
    assert tuple(item.tool for item in result.items) == tools
    assert all(item.reason for item in result.items)


def test_missing_prices_is_a_limitation_not_an_invented_series() -> None:
    planned = classify_intent({"query": "计算组合波动率"})
    assert planned["classified_intent"] == ResearchIntent.RISK
    assert planned["plan_limitations"]
    assert route_after_classify(planned) == "execute_tools"
    with_prices = classify_intent({"query": "计算组合波动率", "prices": [100, 101, 99]})
    assert with_prices["plan_limitations"] == ()
    assert route_after_classify(with_prices | {"prices": [100, 101, 99]}) == "execute_tools"


def test_graph_carries_structured_plan_without_running_document_or_query_tools() -> None:
    result = research_graph.invoke({"query": "比较年报披露的营业收入与财务数据"})
    assert result["classified_intent"] == ResearchIntent.MIXED
    assert len(result["plan_items"]) == 2
    assert len(result["tool_results"]) == 2
    assert all(item.status == "unavailable" for item in result["tool_results"])
    assert "risk_metrics" not in result


def test_http_rejects_invalid_prices_before_graph_execution(agent_auth) -> None:
    response = TestClient(app).post(
        "/api/v1/agent/query",
        headers=agent_auth.headers(),
        json={"query": "计算风险", "prices": [100, 0, 102], "workspace_id": str(agent_auth.workspace_id)},
    )
    assert response.status_code == 422
