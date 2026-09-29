"""Authorized research-brief adapter over the existing graph and review gate."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from finsight.agents.checkpoints import ResearchRun
from finsight.agents.planning import plan_research
from finsight.agents.snapshot import ResearchPhase
from finsight.agents.state import ResearchState
from finsight.domain.mcp_tool_contracts import (
    GenerateResearchBriefInput,
    GenerateResearchBriefOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
    ToolName,
    tool_access_allowed,
)
from finsight.domain.research_flow import ResearchQuestion, ResearchTool
from finsight.services.mcp_document_tool import KnowledgeOwnership
from finsight.services.mcp_tool_audit import ToolAudit

_ROUTE = "/mcp/tools/generate_research_brief"


class ResearchGraph(Protocol):
    def invoke(self, state: ResearchState) -> ResearchState: ...


class ResearchCheckpoints(Protocol):
    def start(self, initial_state: ResearchState) -> ResearchRun: ...


class ResearchBriefTool:
    def __init__(
        self, audit: ToolAudit, graph: ResearchGraph,
        ownership: KnowledgeOwnership | None = None,
        checkpoints: ResearchCheckpoints | None = None,
    ) -> None:
        self._audit = audit
        self._graph = graph
        self._ownership = ownership
        self._checkpoints = checkpoints

    def execute(
        self, context: ToolCallContext, payload: GenerateResearchBriefInput,
    ) -> GenerateResearchBriefOutput | ToolFailure:
        try:
            self._audit.begin(
                context.request_id, action=ToolName.GENERATE_RESEARCH_BRIEF.value,
                method="MCP", route_pattern=_ROUTE, target_id=None,
            )
        except Exception:  # noqa: BLE001 - no research execution without audit
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")

        status_code = 500
        outcome: GenerateResearchBriefOutput | ToolFailure
        try:
            if not tool_access_allowed(
                context, ToolName.GENERATE_RESEARCH_BRIEF,
                workspace_id=payload.workspace_id,
                knowledge_base_id=payload.knowledge_base_id,
                release_requested=payload.release_requested,
            ):
                status_code = 403
                outcome = ToolFailure(code=ToolErrorCode.ACCESS_DENIED, message="Access denied")
            elif payload.knowledge_base_id is not None and self._ownership is None:
                status_code = 503
                outcome = ToolFailure(
                    code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Knowledge scope unavailable"
                )
            elif (
                payload.knowledge_base_id is not None
                and self._ownership is not None
                and self._ownership.workspace_for(payload.knowledge_base_id) != payload.workspace_id
            ):
                status_code = 403
                outcome = ToolFailure(code=ToolErrorCode.ACCESS_DENIED, message="Access denied")
            else:
                planned = plan_research(
                    ResearchQuestion(query=payload.query, prices=payload.prices)
                )
                needs_documents = any(
                    item.tool == ResearchTool.DOCUMENT_SEARCH for item in planned.items
                )
                if needs_documents and payload.knowledge_base_id is None:
                    status_code = 422
                    outcome = ToolFailure(
                        code=ToolErrorCode.INVALID_INPUT, message="Knowledge base required"
                    )
                elif payload.release_requested and self._checkpoints is None:
                    status_code = 503
                    outcome = ToolFailure(
                        code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Review storage unavailable"
                    )
                else:
                    outcome = self._run_research(context, payload)
                    status_code = 202 if outcome.review_pending else 200
        except (ValueError, ValidationError):
            status_code = 422
            outcome = ToolFailure(code=ToolErrorCode.INVALID_INPUT, message="Invalid research request")
        except Exception:  # noqa: BLE001 - no raw question, tool output or checkpoint error
            outcome = ToolFailure(code=ToolErrorCode.INTERNAL_ERROR, message="Research brief failed")

        try:
            self._audit.finish(
                context.request_id, status_code=status_code,
                actor_user_id=context.principal.user_id, workspace_id=payload.workspace_id,
                knowledge_base_id=payload.knowledge_base_id,
            )
        except Exception:  # noqa: BLE001 - do not release draft without completed audit
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")
        return outcome

    def _run_research(
        self, context: ToolCallContext, payload: GenerateResearchBriefInput,
    ) -> GenerateResearchBriefOutput:
        state: ResearchState = {
            "query": payload.query,
            "workspace_id": str(payload.workspace_id),
            "owner_user_id": str(context.principal.user_id),
        }
        if payload.knowledge_base_id is not None:
            state["knowledge_base_id"] = str(payload.knowledge_base_id)
        if payload.prices is not None:
            state["prices"] = list(payload.prices)
        if payload.release_requested:
            state["release_requested"] = True

        if self._checkpoints is not None:
            run = self._checkpoints.start(state)
            answer = run.snapshot.answer_result
            pending = run.snapshot.phase == ResearchPhase.AWAITING_REVIEW
            if answer is None or (payload.release_requested and not pending):
                raise RuntimeError("research checkpoint did not reach the expected phase")
            return GenerateResearchBriefOutput(
                answer_status=answer.status,
                answer=None if pending else answer.text,
                limitations=answer.limitations,
                review_pending=pending,
                thread_id=UUID(run.thread_id),
            )

        result = self._graph.invoke(state)
        answer = result["answer_result"]
        return GenerateResearchBriefOutput(
            answer_status=answer.status, answer=answer.text,
            limitations=answer.limitations,
        )
