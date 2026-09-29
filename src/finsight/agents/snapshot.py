"""Versioned JSON boundary for persisted research graph state."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from finsight.agents.state import ResearchState
from finsight.agents.tools import ToolExecution
from finsight.domain.query_plan import StructuredQueryPlan
from finsight.domain.research_flow import (
    ResearchAnswer,
    ResearchIntent,
    ResearchPlanItem,
    ResearchQuestion,
    ResearchToolResult,
    ToolOutputSummary,
)
from finsight.domain.research_review import ReviewDecision
from finsight.domain.schemas import RiskMetrics
from finsight.services.evidence_search import EvidenceSearchResult
from finsight.services.query_planning import query_digest
from finsight.services.structured_query import StructuredQueryOutcome


class ResearchPhase(StrEnum):
    SUBMITTED = "submitted"
    PLANNED = "planned"
    TOOLS_COMPLETE = "tools_complete"
    AWAITING_REVIEW = "awaiting_review"
    FINISHED = "finished"


class ResearchStateSnapshot(BaseModel):
    """Only values needed for a future resume, never live service result objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    phase: ResearchPhase
    question: ResearchQuestion
    workspace_id: UUID | None = None
    knowledge_base_id: UUID | None = None
    owner_user_id: UUID | None = None
    release_requested: bool = False
    review_request: dict[str, object] | None = None
    review_outcome: dict[str, str] | None = None
    structured_plan: StructuredQueryPlan | None = None
    intent: ResearchIntent | None = None
    plan_items: tuple[ResearchPlanItem, ...] = ()
    plan_limitations: tuple[str, ...] = ()
    tool_results: tuple[ResearchToolResult, ...] = ()
    output_summaries: tuple[ToolOutputSummary, ...] = ()
    risk_metrics: RiskMetrics | None = None
    answer_result: ResearchAnswer | None = None

    @model_validator(mode="after")
    def validate_phase(self) -> ResearchStateSnapshot:
        if (
            self.structured_plan is not None
            and self.structured_plan.query_sha256 != query_digest(self.question.query)
        ):
            raise ValueError("structured plan must match the saved question")
        if (self.workspace_id is None) != (self.owner_user_id is None):
            raise ValueError("workspace and owner must be recorded together")
        if self.knowledge_base_id is not None and self.workspace_id is None:
            raise ValueError("knowledge base requires a workspace")
        if self.phase != ResearchPhase.SUBMITTED and self.intent is None:
            raise ValueError("planned or later state requires an intent")
        if self.phase == ResearchPhase.SUBMITTED and (
            self.intent is not None
            or self.plan_items
            or self.plan_limitations
            or self.tool_results
            or self.risk_metrics is not None
            or self.answer_result
        ):
            raise ValueError("submitted state cannot contain execution results")
        if self.phase == ResearchPhase.PLANNED and (
            self.tool_results or self.risk_metrics is not None or self.answer_result
        ):
            raise ValueError("planned state cannot contain execution results")
        if self.phase == ResearchPhase.TOOLS_COMPLETE and self.answer_result is not None:
            raise ValueError("tool-complete state cannot contain a final answer")
        if self.phase in {ResearchPhase.AWAITING_REVIEW, ResearchPhase.FINISHED} and self.answer_result is None:
            raise ValueError("finished state requires an answer")
        if self.phase == ResearchPhase.AWAITING_REVIEW and (
            not self.release_requested or self.review_request is None or self.review_outcome is not None
        ):
            raise ValueError("awaiting review requires a release request")
        if self.review_outcome is not None:
            ReviewDecision.model_validate(self.review_outcome)
            if self.phase != ResearchPhase.FINISHED or not self.release_requested:
                raise ValueError("review outcome requires a completed release request")
        if self.phase == ResearchPhase.FINISHED and self.release_requested and self.review_outcome is None:
            raise ValueError("completed release request requires a review outcome")
        if (
            self.phase in {ResearchPhase.TOOLS_COMPLETE, ResearchPhase.AWAITING_REVIEW, ResearchPhase.FINISHED}
            and self.intent != ResearchIntent.UNSUPPORTED
            and len(self.tool_results) != len(self.plan_items)
        ):
            raise ValueError("completed tool results must match the plan")
        if any(item.tool != result.tool for item, result in zip(
            self.plan_items, self.tool_results, strict=False
        )):
            raise ValueError("tool result order must match the plan")
        if len({summary.tool for summary in self.output_summaries}) != len(self.output_summaries):
            raise ValueError("output summaries must be unique by tool")
        if self.output_summaries and self.phase in {ResearchPhase.SUBMITTED, ResearchPhase.PLANNED}:
            raise ValueError("output summaries require completed tools")
        if any(summary.tool not in {item.tool for item in self.tool_results} for summary in self.output_summaries):
            raise ValueError("output summary does not match the plan")
        return self

    @classmethod
    def from_runtime(cls, state: ResearchState, *, phase: ResearchPhase) -> ResearchStateSnapshot:
        prices = state.get("prices")
        question = ResearchQuestion(
            query=state["query"], prices=tuple(prices) if prices is not None else None
        )
        return cls(
            phase=phase,
            question=question,
            workspace_id=UUID(state["workspace_id"]) if state.get("workspace_id") else None,
            knowledge_base_id=(
                UUID(state["knowledge_base_id"]) if state.get("knowledge_base_id") else None
            ),
            owner_user_id=UUID(state["owner_user_id"]) if state.get("owner_user_id") else None,
            release_requested=state.get("release_requested", False),
            review_request=state.get("review_request"),
            review_outcome=state.get("review_outcome"),
            structured_plan=state.get("structured_plan"),
            intent=state.get("classified_intent"),
            plan_items=state.get("plan_items", ()),
            plan_limitations=state.get("plan_limitations", ()),
            tool_results=state.get("tool_results", ()),
            output_summaries=state.get("output_summaries", ()),
            risk_metrics=state.get("risk_metrics"),
            answer_result=state.get("answer_result"),
        )

    def to_runtime(self) -> ResearchState:
        state: ResearchState = {"query": self.question.query}
        if self.workspace_id is not None and self.owner_user_id is not None:
            state["workspace_id"] = str(self.workspace_id)
            state["owner_user_id"] = str(self.owner_user_id)
        if self.knowledge_base_id is not None:
            state["knowledge_base_id"] = str(self.knowledge_base_id)
        if self.release_requested:
            state["release_requested"] = True
        if self.review_request is not None:
            state["review_request"] = self.review_request
        if self.review_outcome is not None:
            state["review_outcome"] = self.review_outcome
        if self.question.prices is not None:
            state["prices"] = list(self.question.prices)
        if self.structured_plan is not None:
            state["structured_plan"] = self.structured_plan
        if self.intent is not None:
            state["classified_intent"] = self.intent
            state["intent"] = self.intent.value
            state["plan_items"] = self.plan_items
            state["plan"] = [item.reason for item in self.plan_items]
            state["plan_limitations"] = self.plan_limitations
        if self.phase in {ResearchPhase.TOOLS_COMPLETE, ResearchPhase.AWAITING_REVIEW, ResearchPhase.FINISHED}:
            state["tool_results"] = self.tool_results
            state["output_summaries"] = self.output_summaries
        if self.risk_metrics is not None:
            state["risk_metrics"] = self.risk_metrics
        if self.answer_result is not None:
            state["answer_result"] = self.answer_result
            state["final_answer"] = self.answer_result.text
        return state


def summarize_tool_output(execution: ToolExecution) -> ToolOutputSummary | None:
    output = execution.output
    if isinstance(output, EvidenceSearchResult):
        return ToolOutputSummary(
            tool=execution.result.tool,
            reference_sha256=output.bundle.query_sha256,
            record_count=len(output.bundle.citations),
        )
    if isinstance(output, StructuredQueryOutcome):
        return ToolOutputSummary(
            tool=execution.result.tool,
            reference_sha256=output.execution.sql_sha256,
            record_count=output.execution.row_count,
        )
    if isinstance(output, RiskMetrics):
        digest = sha256(output.model_dump_json().encode("utf-8")).hexdigest()
        return ToolOutputSummary(
            tool=execution.result.tool,
            reference_sha256=digest,
            record_count=output.observations,
        )
    return None
