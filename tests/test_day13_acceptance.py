"""Cross-node HTTP scenarios; controlled sources are not real-market acceptance."""

from datetime import date
from decimal import Decimal
from hashlib import sha256

from fastapi.testclient import TestClient

from finsight.agents.graph import build_research_graph
from finsight.agents.tools import ResearchToolAdapter, ToolExecution
from finsight.domain.claim_evidence import (
    ClaimContext,
    DocumentEvidencePointer,
    QueryEvidencePointer,
)
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
from finsight.domain.query_plan import PlanStatus, QueryIntent
from finsight.domain.research_flow import ResearchTool, ResearchToolResult, ToolStatus
from finsight.main import app
from finsight.services.query_planning import build_query_plan


class DocumentStub:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.calls = 0
        self.unavailable = unavailable

    def search(self, query: str, *, criteria=None):
        self.calls += 1
        if self.unavailable:
            raise ConnectionError("temporary document outage")
        return object()


class StructuredStub:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, plan):
        self.calls += 1
        return object()


def test_http_mixed_flow_keeps_partial_success_out_of_final_conclusion(agent_auth) -> None:
    query = "比较年报收入与财务数据"
    plan = build_query_plan(query, status=PlanStatus.READY, intent=QueryIntent.COMPANY_LOOKUP)
    document = DocumentStub(unavailable=True)
    structured = StructuredStub()
    previous = app.state.research_graph
    app.state.research_graph = build_research_graph(
        ResearchToolAdapter(document_search=document, structured_query=structured)
    )
    try:
        response = TestClient(app).post(
            "/api/v1/agent/query",
            headers=agent_auth.headers(),
            json={
                "query": query,
                "structured_plan": plan.model_dump(mode="json"),
                "workspace_id": str(agent_auth.workspace_id),
                "knowledge_base_id": str(agent_auth.knowledge_base_id),
            },
        )
    finally:
        app.state.research_graph = previous
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "mixed_research"
    assert body["answer_status"] == "insufficient_evidence"
    assert body["risk_metrics"] is None
    assert body["evidence"] == []
    assert any("DocumentSearchUnavailable" in item for item in body["limitations"])
    assert document.calls == 2  # Only transient failure is retried once.
    assert structured.calls == 1


def test_http_missing_risk_prices_and_unsupported_question_have_distinct_outcomes(agent_auth) -> None:
    client = TestClient(app)
    missing = client.post(
        "/api/v1/agent/query", headers=agent_auth.headers(),
        json={"query": "计算组合波动率", "workspace_id": str(agent_auth.workspace_id)},
    )
    assert missing.status_code == 200
    assert missing.json()["answer_status"] == "insufficient_evidence"
    assert missing.json()["risk_metrics"] is None
    assert any("价格序列" in item for item in missing.json()["limitations"])
    unsupported = client.post(
        "/api/v1/agent/query", headers=agent_auth.headers(),
        json={"query": "推荐附近餐厅", "workspace_id": str(agent_auth.workspace_id)},
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["answer_status"] == "refused"
    assert unsupported.json()["risk_metrics"] is None


def _context(company: str) -> ClaimContext:
    return ClaimContext(
        entity_code=company,
        metric_code="revenue",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        currency="CNY",
    )


class ConflictingEvidenceAdapter(ResearchToolAdapter):
    def execute(self, item, *, query, prices=None, structured_plan=None, knowledge_base_id=None):
        if item.tool == ResearchTool.DOCUMENT_SEARCH:
            quote = "收入为100元"
            evidence = NormalizedEvidence(
                pointer=DocumentEvidencePointer(
                    citation_id="C1", document_id=1, chunk_id=1, chunk_version=1,
                    content_sha256="a" * 64,
                    quoted_text_sha256=sha256(quote.encode()).hexdigest(),
                    page_start=1, page_end=1,
                ),
                context=_context("AAA"),
                source_text=quote,
                grounded_dimensions=(EvidenceDimension.ENTITY,),
            )
        else:
            evidence = NormalizedEvidence(
                pointer=QueryEvidencePointer(
                    query_sha256="b" * 64, sql_sha256="c" * 64,
                    row_index=0, row_sha256="d" * 64,
                ),
                context=_context("BBB"),
                source_text="revenue=100 CNY",
                value=Decimal(100),
                unit="CNY",
                grounded_dimensions=(EvidenceDimension.ENTITY, EvidenceDimension.METRIC),
            )
        return ToolExecution(
            ResearchToolResult(tool=item.tool, status=ToolStatus.SUCCEEDED, evidence=(evidence,))
        )


def test_full_graph_refuses_to_merge_different_companies_even_with_two_successes() -> None:
    result = build_research_graph(ConflictingEvidenceAdapter()).invoke(
        {"query": "比较年报披露收入与财务数据"}
    )
    assert len(result["tool_results"]) == 2
    assert all(item.status == ToolStatus.SUCCEEDED for item in result["tool_results"])
    assert result["answer_result"].status == "insufficient_evidence"
    assert result["answer_result"].limitations == ("EvidenceContextMismatch",)
