"""Day17 Step1: four transport-neutral tools with fail-closed inputs and roles."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.domain.mcp_tool_contracts import (
    CalculatePortfolioRiskInput,
    GenerateResearchBriefInput,
    GenerateResearchBriefOutput,
    QueryFinancialDataInput,
    SearchFinancialDocumentsInput,
    ToolCallContext,
    ToolName,
    tool_access_allowed,
)

USER = UUID(int=1)
WORKSPACE = UUID(int=2)
KNOWLEDGE = UUID(int=3)
OTHER_KNOWLEDGE = UUID(int=4)


def context(role: Role, *, active: bool = True) -> ToolCallContext:
    return ToolCallContext(
        principal=Principal(
            user_id=USER, active=active,
            memberships=(WorkspaceMembership(
                workspace_id=WORKSPACE, role=role, knowledge_base_ids=(KNOWLEDGE,)
            ),),
        ),
        request_id=UUID(int=5),
    )


def test_four_input_schemas_reject_client_role_and_unknown_fields() -> None:
    valid = (
        (SearchFinancialDocumentsInput, {"workspace_id": WORKSPACE, "knowledge_base_id": KNOWLEDGE, "query": "年度报告"}),
        (QueryFinancialDataInput, {"workspace_id": WORKSPACE, "query": "查看营业收入", "intent": "financial_statement"}),
        (CalculatePortfolioRiskInput, {"workspace_id": WORKSPACE, "prices": [100, 99, 101]}),
        (GenerateResearchBriefInput, {"workspace_id": WORKSPACE, "query": "总结风险"}),
    )
    for model, payload in valid:
        model.model_validate(payload)
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "role": "workspace_admin"})


def test_risk_contract_rejects_nonfinite_or_nonpositive_prices() -> None:
    for prices in ([100, 0, 101], [100, float("nan"), 101], [100, float("inf"), 101]):
        with pytest.raises(ValidationError):
            CalculatePortfolioRiskInput(workspace_id=WORKSPACE, prices=prices)
    with pytest.raises(ValidationError):
        CalculatePortfolioRiskInput(workspace_id=WORKSPACE, prices=[100, 99, 101], confidence=1)


def test_permissions_are_server_resolved_and_scope_bound() -> None:
    viewer = context(Role.VIEWER)
    researcher = context(Role.RESEARCHER)
    assert tool_access_allowed(
        viewer, ToolName.SEARCH_FINANCIAL_DOCUMENTS,
        workspace_id=WORKSPACE, knowledge_base_id=KNOWLEDGE,
    )
    assert not tool_access_allowed(viewer, ToolName.CALCULATE_PORTFOLIO_RISK, workspace_id=WORKSPACE)
    assert not tool_access_allowed(
        viewer, ToolName.SEARCH_FINANCIAL_DOCUMENTS,
        workspace_id=WORKSPACE, knowledge_base_id=OTHER_KNOWLEDGE,
    )
    assert not tool_access_allowed(
        researcher, ToolName.SEARCH_FINANCIAL_DOCUMENTS, workspace_id=WORKSPACE,
    )
    assert not tool_access_allowed(
        researcher, ToolName.QUERY_FINANCIAL_DATA, workspace_id=UUID(int=99),
    )
    assert not tool_access_allowed(
        context(Role.RESEARCHER, active=False), ToolName.GENERATE_RESEARCH_BRIEF,
        workspace_id=WORKSPACE,
    )
    assert tool_access_allowed(
        researcher, ToolName.GENERATE_RESEARCH_BRIEF,
        workspace_id=WORKSPACE, release_requested=True,
    )
    assert not tool_access_allowed(
        researcher, ToolName.CALCULATE_PORTFOLIO_RISK,
        workspace_id=WORKSPACE, release_requested=True,
    )


def test_pending_brief_cannot_expose_final_answer() -> None:
    with pytest.raises(ValidationError):
        GenerateResearchBriefOutput(
            answer_status="insufficient_evidence", answer="未经确认的结论",
            review_pending=True, thread_id=UUID(int=8),
        )
    pending = GenerateResearchBriefOutput(
        answer_status="insufficient_evidence", limitations=("待核验",),
        review_pending=True, thread_id=UUID(int=8),
    )
    assert pending.answer is None
