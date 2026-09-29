"""Aggregate only observed, allowlisted trace events into local runtime metrics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from math import ceil
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.research_flow import AnswerStatus, ResearchTool, ToolStatus
from finsight.services.structured_trace import TraceEvent, TraceKind


class ToolRuntimeMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: ResearchTool
    executions: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    failed: int = Field(ge=0)
    duration_p95_ms: float | None = None


class RuntimeMetricsReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = "local_trace_jsonl"
    http_requests: int = Field(ge=0)
    http_2xx: int = Field(ge=0)
    http_4xx: int = Field(ge=0)
    http_5xx: int = Field(ge=0)
    http_5xx_rate: float | None = None
    http_duration_p50_ms: float | None = None
    http_duration_p95_ms: float | None = None
    research_completed: int = Field(ge=0)
    research_answered: int = Field(ge=0)
    research_insufficient_evidence: int = Field(ge=0)
    research_refused: int = Field(ge=0)
    review_pending: int = Field(ge=0)
    tool_executions: int = Field(ge=0)
    tool_unavailable: int = Field(ge=0)
    tool_failed: int = Field(ge=0)
    tools: tuple[ToolRuntimeMetrics, ...] = ()
    incomplete_request_ids: int = Field(ge=0)
    token_usage: None = None
    estimated_cost: None = None


def _nearest_rank(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * fraction) - 1)]


def aggregate_runtime_metrics(events: Iterable[TraceEvent]) -> RuntimeMetricsReport:
    """Use completed events as denominators; never turn missing observations into success."""
    http_ids: set[UUID] = set()
    observed_ids: set[UUID] = set()
    http_status: Counter[int] = Counter()
    answers: Counter[AnswerStatus] = Counter()
    tool_status: dict[ResearchTool, Counter[ToolStatus]] = {}
    tool_durations: dict[ResearchTool, list[float]] = {}
    http_durations: list[float] = []
    research_count = pending_count = 0

    for event in events:
        observed_ids.add(event.request_id)
        if event.kind == TraceKind.HTTP_COMPLETED:
            if event.request_id in http_ids:
                raise ValueError("duplicate HTTP completion for one request")
            if event.status_code is None or event.duration_ms is None:
                raise ValueError("HTTP completion lacks status or duration")
            http_ids.add(event.request_id)
            http_status[event.status_code // 100] += 1
            http_durations.append(event.duration_ms)
        elif event.kind == TraceKind.RESEARCH_COMPLETED:
            if event.answer_status is None or event.review_pending is None:
                raise ValueError("research completion lacks answer status or review state")
            research_count += 1
            answers[event.answer_status] += 1
            pending_count += int(event.review_pending)
        elif event.kind == TraceKind.TOOL_COMPLETED:
            if event.tool is None or event.tool_status is None or event.duration_ms is None:
                raise ValueError("tool completion lacks tool, status or duration")
            tool_status.setdefault(event.tool, Counter())[event.tool_status] += 1
            tool_durations.setdefault(event.tool, []).append(event.duration_ms)

    tools = tuple(
        ToolRuntimeMetrics(
            tool=tool,
            executions=sum(statuses.values()),
            succeeded=statuses[ToolStatus.SUCCEEDED],
            unavailable=statuses[ToolStatus.UNAVAILABLE],
            failed=statuses[ToolStatus.FAILED],
            duration_p95_ms=_nearest_rank(tool_durations[tool], 0.95),
        )
        for tool, statuses in sorted(tool_status.items(), key=lambda pair: pair[0].value)
    )
    total_http = len(http_ids)
    return RuntimeMetricsReport(
        http_requests=total_http,
        http_2xx=http_status[2],
        http_4xx=http_status[4],
        http_5xx=http_status[5],
        http_5xx_rate=http_status[5] / total_http if total_http else None,
        http_duration_p50_ms=_nearest_rank(http_durations, 0.5),
        http_duration_p95_ms=_nearest_rank(http_durations, 0.95),
        research_completed=research_count,
        research_answered=answers[AnswerStatus.ANSWERED],
        research_insufficient_evidence=answers[AnswerStatus.INSUFFICIENT_EVIDENCE],
        research_refused=answers[AnswerStatus.REFUSED],
        review_pending=pending_count,
        tool_executions=sum(item.executions for item in tools),
        tool_unavailable=sum(item.unavailable for item in tools),
        tool_failed=sum(item.failed for item in tools),
        tools=tools,
        incomplete_request_ids=len(observed_ids - http_ids),
    )
