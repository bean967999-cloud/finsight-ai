"""Day13 Step1: explicit workflow boundary and state contract."""

import pytest
from pydantic import ValidationError

from finsight.agents.state import ResearchState
from finsight.domain.research_flow import (
    AnswerStatus,
    ResearchAnswer,
    ResearchIntent,
    ResearchPlanItem,
    ResearchQuestion,
    ResearchTool,
    ResearchToolResult,
    ToolStatus,
)


def test_question_rejects_empty_or_invalid_price_series() -> None:
    assert ResearchQuestion(query="  比较年度收入  ").query == "比较年度收入"
    for prices in ((1.0, 2.0), (1.0, 2.0, 0.0), (1.0, float("nan"), 3.0)):
        with pytest.raises(ValidationError):
            ResearchQuestion(query="计算波动率", prices=prices)
    with pytest.raises(ValidationError):
        ResearchQuestion(query=" ")


def test_plan_and_result_distinguish_success_empty_from_failure() -> None:
    step = ResearchPlanItem(tool=ResearchTool.DOCUMENT_SEARCH, reason="需要定位年报原文")
    assert step.tool == ResearchTool.DOCUMENT_SEARCH
    empty = ResearchToolResult(tool=step.tool, status=ToolStatus.SUCCEEDED)
    assert empty.evidence == () and empty.error_code is None
    outage = ResearchToolResult(
        tool=step.tool,
        status=ToolStatus.UNAVAILABLE,
        error_code="DocumentServiceUnavailable",
    )
    assert outage.status != empty.status
    with pytest.raises(ValidationError, match="requires an error code"):
        ResearchToolResult(tool=step.tool, status=ToolStatus.FAILED)
    with pytest.raises(ValidationError, match="cannot contain an error code"):
        ResearchToolResult(tool=step.tool, status=ToolStatus.SUCCEEDED, error_code="bad")


def test_nonanswer_must_explain_why() -> None:
    with pytest.raises(ValidationError, match="explicit limitation"):
        ResearchAnswer(status=AnswerStatus.INSUFFICIENT_EVIDENCE, text="暂无可靠结论")
    answer = ResearchAnswer(
        status=AnswerStatus.REFUSED,
        text="无法提供该结论",
        limitations=("问题超出已接入数据范围",),
    )
    assert answer.status == AnswerStatus.REFUSED


def test_graph_state_can_carry_structured_contract_without_breaking_legacy_fields() -> None:
    state: ResearchState = {
        "query": "比较营业收入",
        "classified_intent": ResearchIntent.STRUCTURED,
        "plan_items": (
            ResearchPlanItem(tool=ResearchTool.STRUCTURED_QUERY, reason="核对结构化数据"),
        ),
        "tool_results": (),
        "answer_result": ResearchAnswer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            text="没有可核对的数据",
            limitations=("结构化查询尚未执行",),
        ),
    }
    assert state["query"] == "比较营业收入"
    assert state["classified_intent"] == ResearchIntent.STRUCTURED
