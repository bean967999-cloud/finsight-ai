"""Two-stage audit trail: a request is recorded before sensitive work begins."""

from collections.abc import Callable
from datetime import UTC, datetime
from re import fullmatch
from uuid import UUID

from sqlalchemy.orm import Session

from finsight.infrastructure.database.models.audit_event import AuditEvent


def audit_target(method: str, path: str) -> tuple[str, str, str | None] | None:
    """Return fixed action/route labels; never persist the raw URL or query string."""
    fixed = {
        ("POST", "/api/v1/auth/login"): ("auth_login", "/api/v1/auth/login"),
        ("POST", "/api/v1/agent/query"): ("research_submit", "/api/v1/agent/query"),
        ("POST", "/api/v1/evidence/search"): ("evidence_search", "/api/v1/evidence/search"),
        ("POST", "/api/v1/jobs"): ("document_job_submit", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/documents"): ("scoped_document_list", "/api/v1/jobs/documents"),
        ("POST", "/api/v1/jobs/documents/upload"): ("scoped_document_upload", "/api/v1/jobs/documents/upload"),
        ("POST", "/api/v1/jobs/documents/chunks"): ("scoped_chunk_prepare", "/api/v1/jobs/documents/chunks"),
        ("POST", "/api/v1/risk/analyze"): ("risk_calculate", "/api/v1/risk/analyze"),
        ("POST", "/api/v1/risk/asset-report"): ("risk_asset_report", "/api/v1/risk/asset-report"),
        ("POST", "/api/v1/risk/portfolio-report"): (
            "risk_portfolio_report", "/api/v1/risk/portfolio-report"
        ),
        ("POST", "/api/v1/risk/asset-report/from-db"): (
            "public_asset_risk_read", "/api/v1/risk/asset-report/from-db"
        ),
        ("POST", "/api/v1/risk/portfolio-report/from-db"): (
            "public_portfolio_risk_read", "/api/v1/risk/portfolio-report/from-db"
        ),
        ("GET", "/api/v1/evaluation/overview"): (
            "evaluation_overview_read", "/api/v1/evaluation/overview"
        ),
        ("POST", "/api/v1/evaluation/retrieval-runs"): (
            "real_document_evaluation_run", "/api/v1/evaluation/retrieval-runs"
        ),
    }
    selected = fixed.get((method, path))
    if selected is not None:
        return (*selected, None)
    audit_read = fullmatch(r"/api/v1/admin/workspaces/([0-9a-fA-F-]{36})/audit", path)
    if method == "GET" and audit_read is not None:
        return "workspace_audit_read", "/api/v1/admin/workspaces/{workspace_id}/audit", None
    trace_read = fullmatch(r"/api/v1/agent/traces/([0-9a-fA-F-]{36})", path)
    if method == "GET" and trace_read is not None:
        return "research_trace_read", "/api/v1/agent/traces/{request_id}", None
    review = fullmatch(r"/api/v1/agent/threads/([0-9a-fA-F-]{36})/review", path)
    if method == "POST" and review is not None:
        return "review_decide", "/api/v1/agent/threads/{thread_id}/review", review.group(1)
    review_read = fullmatch(r"/api/v1/agent/threads/([0-9a-fA-F-]{36})", path)
    review_content = fullmatch(r"/api/v1/agent/threads/([0-9a-fA-F-]{36})/content", path)
    if method == "GET" and review_content is not None:
        return "review_content_read", "/api/v1/agent/threads/{thread_id}/content", review_content.group(1)
    if method == "GET" and review_read is not None:
        return "review_read", "/api/v1/agent/threads/{thread_id}", review_read.group(1)
    job_read = fullmatch(r"/api/v1/jobs/([0-9]+)", path)
    if method == "GET" and job_read is not None:
        return "document_job_read", "/api/v1/jobs/{job_id}", job_read.group(1)
    return None


class OperationAuditService:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._sessions = session_factory

    def begin(
        self, request_id: UUID, *, action: str, method: str,
        route_pattern: str, target_id: str | None,
    ) -> None:
        with self._sessions() as session, session.begin():
            session.add(AuditEvent(
                request_id=request_id, action=action, method=method,
                route_pattern=route_pattern, target_id=target_id,
                outcome="started",
            ))

    def finish(
        self, request_id: UUID, *, status_code: int,
        actor_user_id: UUID | None = None,
        workspace_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> None:
        with self._sessions() as session, session.begin():
            event = session.get(AuditEvent, request_id)
            if event is None or event.outcome != "started":
                raise RuntimeError("audit request was not started")
            event.actor_user_id = actor_user_id
            event.workspace_id = workspace_id
            event.knowledge_base_id = knowledge_base_id
            event.status_code = status_code
            event.outcome = (
                "succeeded" if status_code < 400 else
                "denied" if status_code in {401, 403} else "failed"
            )
            event.finished_at = datetime.now(UTC)
