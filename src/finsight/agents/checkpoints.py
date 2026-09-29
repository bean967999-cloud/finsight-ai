"""PostgreSQL-backed graph checkpoints identified by server-generated thread IDs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from threading import RLock
from typing import Any, cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command
from psycopg import Connection
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from finsight.agents.graph import build_research_graph
from finsight.agents.snapshot import ResearchPhase, ResearchStateSnapshot
from finsight.agents.state import ResearchState
from finsight.agents.tools import ResearchToolAdapter
from finsight.domain.research_review import ReviewDecision

_ALLOWED_CHECKPOINT_TYPES = (
    ("finsight.domain.research_flow", "ResearchPlanItem"),
    ("finsight.domain.research_flow", "ResearchToolResult"),
    ("finsight.domain.research_flow", "ToolOutputSummary"),
    ("finsight.domain.research_flow", "ResearchAnswer"),
    ("finsight.domain.schemas", "RiskMetrics"),
    ("finsight.domain.query_plan", "StructuredQueryPlan"),
    ("finsight.domain.query_plan", "EntitySelection"),
    ("finsight.domain.query_plan", "MetricRequest"),
    ("finsight.domain.query_plan", "TimeSelection"),
    ("finsight.domain.query_plan", "QueryOrder"),
    ("finsight.domain.normalized_evidence", "NormalizedEvidence"),
    ("finsight.domain.claim_evidence", "ClaimContext"),
    ("finsight.domain.claim_evidence", "DocumentEvidencePointer"),
    ("finsight.domain.claim_evidence", "QueryEvidencePointer"),
    ("finsight.domain.claim_evidence", "RiskEvidencePointer"),
)


def make_research_saver(connection: Connection[dict[str, Any]]) -> PostgresSaver:
    """Use an explicit deserialization allowlist, not permissive msgpack loading."""
    serializer = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_CHECKPOINT_TYPES)
    return PostgresSaver(connection, serde=serializer)


@dataclass(frozen=True, slots=True)
class ResearchRun:
    thread_id: str
    snapshot: ResearchStateSnapshot


class ReviewNotFoundError(LookupError):
    """The supplied thread ID has no saved research flow."""


class ReviewConflictError(ValueError):
    """The flow is not waiting for a review decision."""


class ResearchCheckpointService:
    def __init__(
        self,
        saver: PostgresSaver,
        tools: ResearchToolAdapter | None = None,
        *,
        database_url: str | None = None,
    ) -> None:
        self._graph = build_research_graph(tools, checkpointer=saver)
        self._lock = RLock()
        self._database_url = database_url

    def start(self, initial_state: ResearchState) -> ResearchRun:
        thread_id = str(uuid4())
        with self._lock:
            self._graph.invoke(initial_state, self._config(thread_id))
            saved = self._graph.get_state(self._config(thread_id))
            snapshot = ResearchStateSnapshot.from_runtime(
                cast(ResearchState, saved.values), phase=self._phase(saved)
            )
        return ResearchRun(thread_id, snapshot)

    def get(self, thread_id: str) -> ResearchStateSnapshot | None:
        UUID(thread_id)
        with self._lock:
            saved = self._graph.get_state(self._config(thread_id))
        if not saved.values:
            return None
        state = cast(ResearchState, saved.values)
        return ResearchStateSnapshot.from_runtime(state, phase=self._phase(saved))

    def resume(self, thread_id: str, decision: ReviewDecision) -> ResearchRun:
        UUID(thread_id)
        # An in-process lock protects a shared saver connection. PostgreSQL's
        # transaction-scoped advisory lock also serializes separate workers.
        with self._lock, self._review_lock(thread_id):
            saved = self._graph.get_state(self._config(thread_id))
            if not saved.values:
                raise ReviewNotFoundError(thread_id)
            if self._phase(saved) != ResearchPhase.AWAITING_REVIEW:
                raise ReviewConflictError("review was already handled or never requested")
            self._graph.invoke(Command(resume=decision.model_dump(mode="json")), self._config(thread_id))
            completed = self._graph.get_state(self._config(thread_id))
            if completed.next:
                raise RuntimeError("review did not complete")
            snapshot = ResearchStateSnapshot.from_runtime(
                cast(ResearchState, completed.values), phase=self._phase(completed)
            )
            return ResearchRun(thread_id, snapshot)

    @contextmanager
    def _review_lock(self, thread_id: str) -> Iterator[None]:
        if self._database_url is None:
            with nullcontext():
                yield
            return
        url = make_url(self._database_url).set(drivername="postgresql")
        # UUID high bits fit PostgreSQL's signed bigint advisory-lock key.
        key = (UUID(thread_id).int >> 64) - (1 << 63)
        with Connection.connect(url.render_as_string(hide_password=False)) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            yield

    @staticmethod
    def _phase(saved: Any) -> ResearchPhase:
        state = saved.values
        return (
            ResearchPhase.AWAITING_REVIEW if "review_gate" in saved.next
            else
            ResearchPhase.FINISHED if "answer_result" in state
            else ResearchPhase.TOOLS_COMPLETE if "tool_results" in state
            else ResearchPhase.PLANNED if "classified_intent" in state
            else ResearchPhase.SUBMITTED
        )

    @staticmethod
    def _config(thread_id: str) -> RunnableConfig:
        return RunnableConfig(configurable={"thread_id": thread_id})


@contextmanager
def project_checkpoint_connection(database_url: str) -> Iterator[Connection[dict[str, Any]]]:
    """Open one dedicated psycopg connection; caller decides when to run setup()."""
    url = make_url(database_url).set(drivername="postgresql")
    with Connection.connect(
        url.render_as_string(hide_password=False),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    ) as connection:
        yield connection
