"""Admin-only read endpoint for recomputed local evaluation, not online performance."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from finsight.api.knowledge_access import require_knowledge_access
from finsight.api.routes.auth import get_current_principal
from finsight.domain.access_control import Action, Role
from finsight.services.evaluation_overview import EvaluationOverview, build_evaluation_overview
from finsight.services.real_document_evaluation import EvaluationDatasetChanged

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])


@router.get("/overview", response_model=EvaluationOverview)
def evaluation_overview(request: Request, workspace_id: UUID | None = None) -> EvaluationOverview:
    principal = get_current_principal(request)
    if not any(item.role == Role.WORKSPACE_ADMIN for item in principal.memberships):
        raise HTTPException(403, "仅工作空间管理员可查看评估摘要")
    try:
        overview = build_evaluation_overview()
        selected = next(
            (
                m
                for m in principal.memberships
                if m.role == Role.WORKSPACE_ADMIN
                and (workspace_id is None or m.workspace_id == workspace_id)
            ),
            None,
        )
        if selected is None:
            raise HTTPException(403, "无权查看目标空间评估")
        service = getattr(request.app.state, "real_document_evaluation", None)
        if service:
            overview = overview.model_copy(update={"retrieval": service.pending_report()})
        try:
            record = service.load(selected.workspace_id) if service else None
        except EvaluationDatasetChanged:
            record = None  # Show the current dataset as not-run, never an obsolete score.
        if record:
            actual_workspace = require_knowledge_access(
                request, principal, record.knowledge_base_id, Action.KNOWLEDGE_MANAGE
            )
            if actual_workspace != selected.workspace_id:
                raise HTTPException(403, "评估知识库归属不匹配")
            overview = overview.model_copy(
                update={
                    "retrieval": service.report(record),
                    "retrieval_run": {
                        "run_id": str(record.run_id),
                        "executed_at": record.executed_at.isoformat(),
                        "source": record.source,
                        "workspace_id": str(record.workspace_id),
                        "knowledge_base_id": str(record.knowledge_base_id),
                    },
                }
            )
        return overview
    except (OSError, ValueError) as error:
        raise HTTPException(503, "评估题集或计算过程不可用") from error


class RealRunRequest(BaseModel):
    knowledge_base_id: UUID


@router.post("/retrieval-runs")
def run_real_retrieval(payload: RealRunRequest, request: Request):
    principal = get_current_principal(request)
    workspace_id = require_knowledge_access(
        request, principal, payload.knowledge_base_id, Action.KNOWLEDGE_MANAGE
    )
    service = getattr(request.app.state, "real_document_evaluation", None)
    if service is None:
        raise HTTPException(503, "真实文档评估未配置")
    try:
        record = service.run(workspace_id, payload.knowledge_base_id)
        return {"run_id": str(record.run_id), "status": "observations_scored"}
    except (ValueError, OSError, RuntimeError) as error:
        raise HTTPException(503, "真实评估失败，未发布新结果") from error
