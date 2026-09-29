"""Local, allowlisted JSON trace events correlated by server request ID."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.research_flow import AnswerStatus, ResearchIntent, ResearchTool, ToolStatus
from finsight.domain.research_review import ReviewChoice


class TraceKind(StrEnum):
    HTTP_COMPLETED = "http_completed"
    RESEARCH_PLAN = "research_plan"
    TOOL_COMPLETED = "tool_completed"
    RESEARCH_COMPLETED = "research_completed"
    REVIEW_COMPLETED = "review_completed"


class TraceEvent(BaseModel):
    """Only bounded diagnostic fields; raw request and business content are forbidden."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    request_id: UUID
    kind: TraceKind
    route_pattern: str | None = Field(default=None, max_length=120)
    method: str | None = Field(default=None, pattern=r"^[A-Z]{2,8}$")
    status_code: int | None = Field(default=None, ge=100, le=599)
    duration_ms: float | None = Field(default=None, ge=0)
    intent: ResearchIntent | None = None
    planned_tools: tuple[ResearchTool, ...] = ()
    limitation_count: int | None = Field(default=None, ge=0)
    tool: ResearchTool | None = None
    tool_status: ToolStatus | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
    answer_status: AnswerStatus | None = None
    review_pending: bool | None = None
    review_choice: ReviewChoice | None = None
    thread_id: UUID | None = None


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None: ...


class JsonLogTraceSink:
    def __init__(self) -> None:
        self._logger = logging.getLogger("finsight.structured_trace")

    def emit(self, event: TraceEvent) -> None:
        self._logger.info(event.model_dump_json(exclude_none=True))


def configure_trace_logging() -> None:
    logger = logging.getLogger("finsight.structured_trace")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_current: ContextVar[tuple[UUID, TraceSink] | None] = ContextVar("finsight_trace", default=None)


@contextmanager
def trace_request(request_id: UUID, sink: TraceSink | None) -> Iterator[None]:
    if sink is None:
        yield
        return
    token = _current.set((request_id, sink))
    try:
        yield
    finally:
        _current.reset(token)


def record_trace(kind: TraceKind, **fields: object) -> None:
    current = _current.get()
    if current is None:
        return
    request_id, sink = current
    try:
        sink.emit(TraceEvent.model_validate({"request_id": request_id, "kind": kind, **fields}))
    except Exception:  # noqa: BLE001 - diagnostic logging must not change a business decision
        logging.getLogger("finsight.structured_trace").warning(
            "structured trace emission failed for request %s", request_id
        )
