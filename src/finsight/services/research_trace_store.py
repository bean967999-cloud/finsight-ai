"""Capture safe events in order and persist only authorized research requests."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from finsight.domain.access_control import ResourceScope
from finsight.infrastructure.database.models.research_trace import ResearchTrace
from finsight.services.structured_trace import TraceEvent, TraceSink


class TraceFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    occurred_at: datetime
    event: TraceEvent


class ResearchTraceSnapshot(BaseModel):
    request_id: UUID
    workspace_id: UUID
    owner_user_id: UUID
    knowledge_base_id: UUID | None
    frames: tuple[TraceFrame, ...]
    truncated: bool


class CaptureTraceSink:
    def __init__(self, downstream: TraceSink | None) -> None:
        self.downstream = downstream
        self.frames: list[TraceFrame] = []
        self.truncated = False
        self._lock = Lock()

    def emit(self, event: TraceEvent) -> None:
        with self._lock:
            if len(self.frames) < 64:
                self.frames.append(TraceFrame(
                    sequence=len(self.frames) + 1, occurred_at=datetime.now(UTC), event=event,
                ))
            else:
                self.truncated = True
        if self.downstream is not None:
            self.downstream.emit(event)


class ResearchTraceStore:
    def __init__(self, sessions: Callable[[], Session]) -> None:
        self._sessions = sessions

    def save(self, request_id: UUID, scope: ResourceScope, capture: CaptureTraceSink) -> None:
        if scope.owner_user_id is None:
            raise ValueError("trace owner is required")
        with self._sessions() as session, session.begin():
            session.add(ResearchTrace(
                request_id=request_id, workspace_id=scope.workspace_id,
                owner_user_id=scope.owner_user_id, knowledge_base_id=scope.knowledge_base_id,
                frames=[frame.model_dump(mode="json") for frame in capture.frames],
                truncated=capture.truncated,
            ))

    def get(self, request_id: UUID) -> ResearchTraceSnapshot | None:
        with self._sessions() as session:
            row = session.get(ResearchTrace, request_id)
            if row is None:
                return None
            return ResearchTraceSnapshot(
                request_id=row.request_id, workspace_id=row.workspace_id,
                owner_user_id=row.owner_user_id, knowledge_base_id=row.knowledge_base_id,
                frames=tuple(TraceFrame.model_validate(item) for item in row.frames),
                truncated=row.truncated,
            )
