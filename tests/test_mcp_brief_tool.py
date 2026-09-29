"""Day17 Step5: research briefs reuse conservative answers and review checkpoints."""

from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver

from finsight.agents.checkpoints import ResearchCheckpointService
from finsight.agents.graph import build_research_graph
from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.domain.mcp_tool_contracts import (
    GenerateResearchBriefInput,
    GenerateResearchBriefOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
)
from finsight.services.mcp_brief_tool import ResearchBriefTool

WORKSPACE = UUID(int=42)
KNOWLEDGE = UUID(int=43)


class MemoryAudit:
    def __init__(self, *, fail_finish=False) -> None:
        self.events = []
        self.fail_finish = fail_finish

    def begin(self, request_id, *, action, method, route_pattern, target_id) -> None:
        self.events.append(("begin", action, method, route_pattern))

    def finish(self, request_id, *, status_code, actor_user_id=None, workspace_id=None, knowledge_base_id=None) -> None:
        if self.fail_finish:
            raise RuntimeError("private audit content")
        self.events.append(("finish", status_code, workspace_id, knowledge_base_id))


class Ownership:
    def __init__(self, workspace=WORKSPACE) -> None:
        self.workspace = workspace

    def workspace_for(self, knowledge_base_id):
        return self.workspace


class CountingGraph:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, state):
        self.calls += 1
        raise RuntimeError("private question or source content")


def context(role=Role.RESEARCHER, *, granted=True) -> ToolCallContext:
    return ToolCallContext(
        principal=Principal(user_id=UUID(int=41), memberships=(WorkspaceMembership(
            workspace_id=WORKSPACE, role=role,
            knowledge_base_ids=(KNOWLEDGE,) if granted else (),
        ),)),
        request_id=UUID(int=44),
    )


def risk_payload(*, release=False) -> GenerateResearchBriefInput:
    return GenerateResearchBriefInput(
        workspace_id=WORKSPACE, query="计算价格波动率",
        prices=(100, 102, 101, 105), release_requested=release,
    )


def test_normal_brief_preserves_insufficient_evidence_and_financial_limitation() -> None:
    audit = MemoryAudit()
    tool = ResearchBriefTool(audit, build_research_graph())
    result = tool.execute(context(), risk_payload())
    assert isinstance(result, GenerateResearchBriefOutput)
    assert result.answer_status == "insufficient_evidence"
    assert result.answer is not None and "波动率" in result.answer
    assert any("来源" in item for item in result.limitations)
    assert result.review_pending is False and result.thread_id is None
    assert audit.events[1][1] == 200


def test_release_request_pauses_without_releasing_draft() -> None:
    audit = MemoryAudit()
    checkpoints = ResearchCheckpointService(InMemorySaver())
    tool = ResearchBriefTool(audit, build_research_graph(), checkpoints=checkpoints)
    result = tool.execute(context(), risk_payload(release=True))
    assert isinstance(result, GenerateResearchBriefOutput)
    assert result.review_pending is True and result.answer is None
    assert result.thread_id is not None
    assert checkpoints.get(str(result.thread_id)).answer_result is not None
    assert audit.events[1][1] == 202


def test_release_without_checkpoints_and_denied_roles_never_invoke_graph() -> None:
    graph = CountingGraph()
    audit = MemoryAudit()
    tool = ResearchBriefTool(audit, graph)
    unavailable = tool.execute(context(), risk_payload(release=True))
    assert isinstance(unavailable, ToolFailure)
    assert unavailable.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert graph.calls == 0

    denied = tool.execute(context(Role.VIEWER), risk_payload())
    assert isinstance(denied, ToolFailure)
    assert denied.code == ToolErrorCode.ACCESS_DENIED
    assert graph.calls == 0


def test_document_brief_requires_authorized_owned_knowledge_base() -> None:
    graph = CountingGraph()
    missing = ResearchBriefTool(MemoryAudit(), graph).execute(
        context(), GenerateResearchBriefInput(workspace_id=WORKSPACE, query="查询年报原文")
    )
    assert isinstance(missing, ToolFailure)
    assert missing.code == ToolErrorCode.INVALID_INPUT

    requested = GenerateResearchBriefInput(
        workspace_id=WORKSPACE, knowledge_base_id=KNOWLEDGE, query="查询年报原文"
    )
    no_grant = ResearchBriefTool(MemoryAudit(), graph, Ownership()).execute(
        context(granted=False), requested
    )
    wrong_owner = ResearchBriefTool(
        MemoryAudit(), graph, Ownership(UUID(int=99))
    ).execute(context(Role.WORKSPACE_ADMIN), requested)
    assert isinstance(no_grant, ToolFailure) and no_grant.code == ToolErrorCode.ACCESS_DENIED
    assert isinstance(wrong_owner, ToolFailure) and wrong_owner.code == ToolErrorCode.ACCESS_DENIED
    assert graph.calls == 0


def test_graph_error_is_sanitized_and_audit_finish_failure_hides_result() -> None:
    failed = ResearchBriefTool(MemoryAudit(), CountingGraph()).execute(context(), risk_payload())
    assert isinstance(failed, ToolFailure)
    assert failed.code == ToolErrorCode.INTERNAL_ERROR
    assert "private" not in failed.model_dump_json()

    hidden = ResearchBriefTool(
        MemoryAudit(fail_finish=True), build_research_graph()
    ).execute(context(), risk_payload())
    assert isinstance(hidden, ToolFailure)
    assert hidden.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert "波动率" not in hidden.model_dump_json()
