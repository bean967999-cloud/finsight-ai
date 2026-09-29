"""Day14 Step1: versioned JSON round trips without raw tool objects."""

import json

import pytest
from pydantic import ValidationError

from finsight.agents.graph import build_research_graph, classify_intent
from finsight.agents.snapshot import ResearchPhase, ResearchStateSnapshot
from finsight.agents.tools import ToolExecution
from finsight.domain.query_plan import PlanStatus, QueryIntent
from finsight.domain.research_flow import ResearchTool, ResearchToolResult, ToolStatus
from finsight.services.query_planning import build_query_plan


def test_submitted_and_planned_state_round_trip() -> None:
    submitted = ResearchStateSnapshot.from_runtime(
        {"query": "计算价格波动率", "prices": [100, 102, 101]},
        phase=ResearchPhase.SUBMITTED,
    )
    assert submitted.to_runtime()["prices"] == [100, 102, 101]
    assert ResearchStateSnapshot.model_validate_json(submitted.model_dump_json()) == submitted

    planned_state = {"query": "计算价格波动率", "prices": [100, 102, 101]}
    planned_state.update(classify_intent(planned_state))
    planned = ResearchStateSnapshot.from_runtime(planned_state, phase=ResearchPhase.PLANNED)
    restored = ResearchStateSnapshot.model_validate_json(planned.model_dump_json()).to_runtime()
    assert restored["classified_intent"] == planned_state["classified_intent"]
    assert restored["plan_items"] == planned_state["plan_items"]


def test_finished_graph_state_restores_answer_but_not_live_tool_objects() -> None:
    finished = build_research_graph().invoke(
        {"query": "计算价格波动率", "prices": [100, 102, 101, 105]}
    )
    assert finished["output_summaries"]
    snapshot = ResearchStateSnapshot.from_runtime(finished, phase=ResearchPhase.FINISHED)
    encoded = snapshot.model_dump_json()
    json.loads(encoded)
    assert "tool_executions" not in encoded
    assert "reference_sha256" in encoded
    assert snapshot.output_summaries[0].tool == ResearchTool.RISK_CALCULATION
    restored = ResearchStateSnapshot.model_validate_json(encoded).to_runtime()
    assert "tool_executions" not in restored
    assert restored["risk_metrics"] == finished["risk_metrics"]
    assert restored["answer_result"] == finished["answer_result"]
    assert restored["final_answer"] == finished["final_answer"]


def test_opaque_service_output_is_excluded_from_checkpoint() -> None:
    state = {"query": "查看年报原文"}
    state.update(classify_intent(state))
    state["tool_results"] = (
        ResearchToolResult(tool=ResearchTool.DOCUMENT_SEARCH, status=ToolStatus.SUCCEEDED),
    )
    state["tool_executions"] = (ToolExecution(state["tool_results"][0], object()),)
    snapshot = ResearchStateSnapshot.from_runtime(state, phase=ResearchPhase.TOOLS_COMPLETE)
    assert snapshot.output_summaries == ()
    assert "object" not in snapshot.model_dump_json()


def test_invalid_phase_plan_and_schema_version_are_rejected() -> None:
    state = {"query": "比较年报收入与财务数据"}
    state.update(classify_intent(state))
    with pytest.raises(ValidationError, match="completed tool results must match"):
        ResearchStateSnapshot.from_runtime(state, phase=ResearchPhase.TOOLS_COMPLETE)
    with pytest.raises(ValidationError, match="finished state requires an answer"):
        ResearchStateSnapshot.from_runtime(state, phase=ResearchPhase.FINISHED)
    submitted = ResearchStateSnapshot.from_runtime(
        {"query": "比较年报收入与财务数据"}, phase=ResearchPhase.SUBMITTED
    )
    payload = submitted.model_dump(mode="json")
    payload["schema_version"] = 2
    with pytest.raises(ValidationError, match="Input should be 1"):
        ResearchStateSnapshot.model_validate(payload)


def test_structured_plan_must_match_saved_question() -> None:
    wrong_plan = build_query_plan(
        "另一个问题", status=PlanStatus.READY, intent=QueryIntent.COMPANY_LOOKUP
    )
    with pytest.raises(ValidationError, match="must match the saved question"):
        ResearchStateSnapshot.from_runtime(
            {"query": "查看财务数据", "structured_plan": wrong_plan},
            phase=ResearchPhase.SUBMITTED,
        )
