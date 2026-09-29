from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from time import perf_counter, sleep
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from finsight.agents.answering import compose_research_answer
from finsight.agents.planning import plan_research
from finsight.agents.snapshot import summarize_tool_output
from finsight.agents.state import ResearchState
from finsight.agents.tools import ResearchToolAdapter, ToolExecution
from finsight.domain.research_flow import (
    ResearchIntent,
    ResearchPlanItem,
    ResearchQuestion,
    ResearchToolResult,
    ToolStatus,
)
from finsight.domain.research_review import ReviewDecision
from finsight.domain.schemas import RiskMetrics
from finsight.services.query_planning import query_digest
from finsight.services.structured_trace import TraceKind, record_trace

logger = logging.getLogger(__name__)
_TRANSIENT_ERRORS = {"DocumentSearchUnavailable", "StructuredQueryUnavailable"}


def classify_intent(state: ResearchState) -> dict:
    prices = state.get("prices")
    question = ResearchQuestion(query=state["query"], prices=tuple(prices) if prices is not None else None)
    planned = plan_research(question)
    return {
        "intent": planned.intent.value,
        "classified_intent": planned.intent,
        "plan_items": planned.items,
        "plan_limitations": planned.limitations,
        "plan": [item.reason for item in planned.items],
    }


def route_after_classify(state: ResearchState) -> str:
    if state["plan_items"]:
        return "execute_tools"
    return "synthesize"


def _run_one(
    adapter: ResearchToolAdapter, item: ResearchPlanItem, state: ResearchState
) -> ToolExecution:
    started = perf_counter()
    execution = _execute_one(adapter, item, state)
    record_trace(
        TraceKind.TOOL_COMPLETED,
        tool=item.tool,
        tool_status=execution.result.status,
        error_code=execution.result.error_code,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return execution


def _execute_one(
    adapter: ResearchToolAdapter, item: ResearchPlanItem, state: ResearchState
) -> ToolExecution:
    prices = state.get("prices")
    for attempt in range(2):
        try:
            execution = adapter.execute(
                item,
                query=state["query"],
                prices=tuple(prices) if prices is not None else None,
                structured_plan=state.get("structured_plan"),
                knowledge_base_id=(
                    UUID(state["knowledge_base_id"]) if state.get("knowledge_base_id") else None
                ),
            )
        except Exception:  # noqa: BLE001 - tool adapters can raise arbitrary errors
            logger.warning("research tool failed unexpectedly: %s", item.tool)
            return ToolExecution(
                ResearchToolResult(
                    tool=item.tool,
                    status=ToolStatus.FAILED,
                    error_code="UnexpectedToolError",
                )
            )
        if (
            execution.result.error_code not in _TRANSIENT_ERRORS
            or attempt == 1
        ):
            return execution
        sleep(0.05)
    raise AssertionError("bounded retry loop must return")


def make_execute_tools(adapter: ResearchToolAdapter):
    def execute_tools(state: ResearchState) -> dict:
        items = state["plan_items"]
        with ThreadPoolExecutor(max_workers=min(3, len(items))) as pool:
            contexts = tuple(copy_context() for _ in items)
            futures = tuple(
                pool.submit(context.run, _run_one, adapter, item, state)
                for context, item in zip(contexts, items, strict=True)
            )
            executions = tuple(future.result() for future in futures)
        update: dict = {
            "tool_results": tuple(execution.result for execution in executions),
            "output_summaries": tuple(
                summary
                for execution in executions
                if (summary := summarize_tool_output(execution)) is not None
            ),
        }
        if state["classified_intent"] == ResearchIntent.RISK and len(executions) == 1:
            output = executions[0].output
            if isinstance(output, RiskMetrics):
                update["risk_metrics"] = output
        return update

    return execute_tools


def synthesize(state: ResearchState) -> dict:
    answer = compose_research_answer(state)
    update: dict = {"answer_result": answer, "final_answer": answer.text}
    if state.get("release_requested"):
        update["review_request"] = {
            "action": "external_finalization_review",
            "question_sha256": query_digest(state["query"]),
            "answer_status": answer.status.value,
            "limitations": list(answer.limitations),
            "tool_statuses": [
                {"tool": result.tool.value, "status": result.status.value}
                for result in state.get("tool_results", ())
            ],
            "notice": "人工确认不等于来源核验，也不授权交易或自动对外发布。",
        }
    return update


def route_after_synthesize(state: ResearchState) -> str:
    return "review_gate" if state.get("release_requested") else "end"


def review_gate(state: ResearchState) -> dict:
    # The node may restart on resume; do not perform side effects before interrupt.
    decision = ReviewDecision.model_validate(interrupt(state["review_request"]))
    return {"review_outcome": decision.model_dump(mode="json")}


def build_research_graph(tools: ResearchToolAdapter | None = None, *, checkpointer=None):
    builder = StateGraph(ResearchState)

    builder.add_node("classify_intent", classify_intent)
    builder.add_node("execute_tools", make_execute_tools(tools or ResearchToolAdapter()))
    builder.add_node("synthesize", synthesize)
    builder.add_node("review_gate", review_gate)

    builder.add_edge(START, "classify_intent")
    builder.add_conditional_edges(
        "classify_intent",
        route_after_classify,
        {
            "execute_tools": "execute_tools",
            "synthesize": "synthesize",
        },
    )
    builder.add_edge("execute_tools", "synthesize")
    builder.add_conditional_edges(
        "synthesize", route_after_synthesize, {"review_gate": "review_gate", "end": END}
    )
    builder.add_edge("review_gate", END)

    return builder.compile(checkpointer=checkpointer)


research_graph = build_research_graph()
