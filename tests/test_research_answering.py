"""Day13 Step5: conservative answer gate for tool status and evidence context."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from finsight.agents.answering import compose_research_answer
from finsight.domain.claim_evidence import ClaimContext, QueryEvidencePointer
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
from finsight.domain.research_flow import (
    AnswerStatus,
    ResearchIntent,
    ResearchPlanItem,
    ResearchTool,
    ResearchToolResult,
    ToolStatus,
)
from finsight.main import app


def _fact(index: int, value: str, *, entity: str = "TEST") -> NormalizedEvidence:
    return NormalizedEvidence(
        pointer=QueryEvidencePointer(
            query_sha256="a" * 64,
            sql_sha256="b" * 64,
            row_index=index,
            row_sha256=f"{index + 1:064x}",
        ),
        context=ClaimContext(
            entity_code=entity,
            metric_code="revenue",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            currency="CNY",
        ),
        source_text=f"revenue={value} CNY",
        value=Decimal(value),
        unit="CNY",
        grounded_dimensions=(
            EvidenceDimension.ENTITY,
            EvidenceDimension.METRIC,
            EvidenceDimension.PERIOD,
            EvidenceDimension.UNIT,
        ),
    )


def _state(*results: ResearchToolResult) -> dict:
    return {
        "classified_intent": ResearchIntent.STRUCTURED,
        "plan_items": (ResearchPlanItem(tool=ResearchTool.STRUCTURED_QUERY, reason="核对收入"),),
        "tool_results": results,
    }


def test_unsupported_question_is_refused_without_tool_calls() -> None:
    answer = compose_research_answer(
        {
            "classified_intent": ResearchIntent.UNSUPPORTED,
            "plan_items": (),
            "plan_limitations": ("不属于金融研究范围",),
        }
    )
    assert answer.status == AnswerStatus.REFUSED
    assert answer.limitations


def test_tool_failure_and_empty_success_are_not_financial_answers() -> None:
    failure = compose_research_answer(
        _state(
            ResearchToolResult(
                tool=ResearchTool.STRUCTURED_QUERY,
                status=ToolStatus.UNAVAILABLE,
                error_code="StructuredPlanRequired",
            )
        )
    )
    assert failure.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert "StructuredPlanRequired" in failure.limitations[0]
    empty = compose_research_answer(
        _state(ResearchToolResult(tool=ResearchTool.STRUCTURED_QUERY, status=ToolStatus.SUCCEEDED))
    )
    assert empty.status == AnswerStatus.INSUFFICIENT_EVIDENCE
    assert empty.limitations == ("NoVerifiedEvidence",)


def test_plan_source_and_duplicate_guards_reject_misleading_evidence() -> None:
    fact = _fact(0, "100")
    wrong_tool = compose_research_answer(
        _state(ResearchToolResult(tool=ResearchTool.DOCUMENT_SEARCH, status=ToolStatus.SUCCEEDED))
    )
    assert wrong_tool.limitations == ("ToolPlanMismatch",)
    duplicate = compose_research_answer(
        _state(
            ResearchToolResult(
                tool=ResearchTool.STRUCTURED_QUERY,
                status=ToolStatus.SUCCEEDED,
                evidence=(fact, fact),
            )
        )
    )
    assert duplicate.limitations == ("DuplicateEvidence",)


def test_context_and_value_disagreements_prevent_a_conclusion() -> None:
    context_mismatch = compose_research_answer(
        _state(
            ResearchToolResult(
                tool=ResearchTool.STRUCTURED_QUERY,
                status=ToolStatus.SUCCEEDED,
                evidence=(_fact(0, "100"), _fact(1, "100", entity="OTHER")),
            )
        )
    )
    assert context_mismatch.limitations == ("EvidenceContextMismatch",)
    disagree = compose_research_answer(
        _state(
            ResearchToolResult(
                tool=ResearchTool.STRUCTURED_QUERY,
                status=ToolStatus.SUCCEEDED,
                evidence=(_fact(0, "100"), _fact(1, "200")),
            )
        )
    )
    assert disagree.limitations == ("EvidenceDisagreement",)
    pending_review = compose_research_answer(
        _state(
            ResearchToolResult(
                tool=ResearchTool.STRUCTURED_QUERY,
                status=ToolStatus.SUCCEEDED,
                evidence=(_fact(0, "100"),),
            )
        )
    )
    assert pending_review.limitations == ("ClaimReviewPending",)


def test_http_exposes_explicit_status_and_unverified_risk_limitation(agent_auth) -> None:
    client = TestClient(app)
    unsupported = client.post(
        "/api/v1/agent/query", headers=agent_auth.headers(),
        json={"query": "推荐附近餐厅", "workspace_id": str(agent_auth.workspace_id)},
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["answer_status"] == "refused"
    risk = client.post(
        "/api/v1/agent/query",
        headers=agent_auth.headers(),
        json={"query": "计算价格波动率", "prices": [100, 102, 101, 105], "workspace_id": str(agent_auth.workspace_id)},
    )
    assert risk.status_code == 200
    assert risk.json()["answer_status"] == "insufficient_evidence"
    assert risk.json()["risk_metrics"]["observations"] == 4
    assert any("来源" in item for item in risk.json()["limitations"])
