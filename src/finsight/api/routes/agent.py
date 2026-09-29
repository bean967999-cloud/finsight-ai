from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from finsight.agents.checkpoints import ReviewConflictError, ReviewNotFoundError
from finsight.agents.graph import research_graph
from finsight.agents.planning import plan_research
from finsight.agents.snapshot import ResearchPhase, ResearchStateSnapshot
from finsight.agents.state import ResearchState
from finsight.api.knowledge_access import require_knowledge_access
from finsight.api.routes.auth import get_current_principal
from finsight.domain.access_control import Action, Principal, ResourceScope, Role, evaluate_access
from finsight.domain.evidence import Citation
from finsight.domain.grounded_document_answer import GenerationReport
from finsight.domain.research_flow import AnswerStatus, ResearchQuestion, ResearchTool
from finsight.domain.research_review import ReviewDecision
from finsight.domain.schemas import AgentRequest, AgentResponse
from finsight.services.generation_answer import authorized_generation_scope
from finsight.services.research_trace_store import ResearchTraceSnapshot
from finsight.services.structured_trace import TraceKind, record_trace

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class ReviewFlowResponse(BaseModel):
    thread_id: str
    phase: ResearchPhase
    intent: str
    answer_status: AnswerStatus
    limitations: tuple[str, ...]
    review_request: dict[str, object] | None
    review_outcome: dict[str, str] | None


class ReviewContentResponse(ReviewFlowResponse):
    answer: str
    citations: tuple[Citation, ...] = ()
    generation: GenerationReport | None = None


def _authorize(principal: Principal, action: Action, scope: ResourceScope) -> None:
    if not evaluate_access(principal, action, scope).allowed:
        raise HTTPException(403, "无权访问此工作空间或执行此操作")


def _saved_scope(snapshot: ResearchStateSnapshot) -> ResourceScope:
    if snapshot.workspace_id is None or snapshot.owner_user_id is None:
        raise HTTPException(403, "旧流程缺少归属信息，不能直接授权")
    return ResourceScope(
        workspace_id=snapshot.workspace_id,
        knowledge_base_id=snapshot.knowledge_base_id,
        owner_user_id=snapshot.owner_user_id,
    )


def _require_checkpoints(request: Request):
    service = getattr(request.app.state, "research_checkpoints", None)
    if service is None:
        raise HTTPException(503, "持久化检查点服务不可用")
    return service


def _review_response(thread_id: str, snapshot: ResearchStateSnapshot) -> ReviewFlowResponse:
    answer = snapshot.answer_result
    if answer is None or snapshot.intent is None:
        raise HTTPException(409, "流程尚无可审核的研究结果")
    return ReviewFlowResponse(
        thread_id=thread_id,
        phase=snapshot.phase,
        intent=snapshot.intent.value,
        answer_status=answer.status,
        limitations=answer.limitations,
        review_request=snapshot.review_request,
        review_outcome=snapshot.review_outcome,
    )


@router.post("/query", response_model=AgentResponse)
def query_agent(payload: AgentRequest, request: Request) -> AgentResponse:
    principal = get_current_principal(request)
    if payload.workspace_id is None:
        raise HTTPException(422, "必须指定工作空间编号")
    request.state.audit_workspace_id = payload.workspace_id
    scope = ResourceScope(workspace_id=payload.workspace_id, owner_user_id=principal.user_id)
    _authorize(principal, Action.RESEARCH_SUBMIT, scope)
    if payload.release_requested:
        _authorize(principal, Action.RELEASE_REQUEST, scope)
    planned = plan_research(ResearchQuestion(query=payload.query, prices=payload.prices))
    record_trace(
        TraceKind.RESEARCH_PLAN,
        intent=planned.intent,
        planned_tools=tuple(item.tool for item in planned.items),
        limitation_count=len(planned.limitations),
    )
    needs_documents = any(item.tool == ResearchTool.DOCUMENT_SEARCH for item in planned.items)
    if needs_documents and payload.knowledge_base_id is None:
        raise HTTPException(422, "文档研究必须指定知识库编号")
    if payload.knowledge_base_id is not None:
        source_workspace = require_knowledge_access(
            request, principal, payload.knowledge_base_id, Action.KNOWLEDGE_READ
        )
        if source_workspace != payload.workspace_id:
            raise HTTPException(403, "知识库不属于目标工作空间")
    initial_state: ResearchState = {
        "query": payload.query,
        "workspace_id": str(payload.workspace_id),
        "owner_user_id": str(principal.user_id),
    }
    request.state.research_trace_scope = ResourceScope(
        workspace_id=payload.workspace_id,
        owner_user_id=principal.user_id,
        knowledge_base_id=payload.knowledge_base_id,
    )
    if payload.knowledge_base_id is not None:
        initial_state["knowledge_base_id"] = str(payload.knowledge_base_id)
    if payload.release_requested:
        initial_state["release_requested"] = True
    if payload.prices:
        initial_state["prices"] = list(payload.prices)
    if payload.structured_plan is not None:
        initial_state["structured_plan"] = payload.structured_plan

    # Scope is server-established only after both workspace and KB checks above.
    # Research tool threads propagate ContextVars via the graph's copy_context().
    with authorized_generation_scope(payload.knowledge_base_id):
        checkpoints = getattr(request.app.state, "research_checkpoints", None)
        if checkpoints is not None:
            run = checkpoints.start(initial_state)
            result = run.snapshot.to_runtime()
            thread_id = run.thread_id
            review_pending = run.snapshot.phase == ResearchPhase.AWAITING_REVIEW
        else:
            if payload.release_requested:
                raise HTTPException(503, "人工确认流程需要持久化检查点服务")
            graph = getattr(request.app.state, "research_graph", research_graph)
            result = graph.invoke(initial_state)
            thread_id = None
            review_pending = False

    record_trace(
        TraceKind.RESEARCH_COMPLETED,
        answer_status=result["answer_result"].status,
        review_pending=review_pending,
        thread_id=UUID(thread_id) if thread_id is not None else None,
    )
    return AgentResponse(
        generation=_generation_report(result.get("tool_results", ())),
        thread_id=thread_id,
        review_pending=review_pending,
        review_request=result.get("review_request") if review_pending else None,
        intent=result["intent"],
        answer="流程已暂停，等待人工确认；尚未对外定稿。"
        if review_pending
        else result["final_answer"],
        answer_status=result["answer_result"].status,
        limitations=result["answer_result"].limitations,
        risk_metrics=None if review_pending else result.get("risk_metrics"),
        evidence=(result.get("rag_evidence") or []) + (result.get("sql_evidence") or []),
        citations=tuple(
            c
            for item in result.get("tool_results", ())
            if item.document_answer
            for c in item.document_answer.citations
        ),
    )


def _generation_report(tool_results):
    return next((
        item.document_answer.generation for item in tool_results
        if item.document_answer is not None and item.document_answer.generation is not None
    ), None)


@router.get("/threads/{thread_id}", response_model=ReviewFlowResponse)
def get_review_flow(thread_id: str, request: Request) -> ReviewFlowResponse:
    principal = get_current_principal(request)
    checkpoints = _require_checkpoints(request)
    try:
        snapshot = checkpoints.get(thread_id)
    except ValueError as error:
        raise HTTPException(422, "无效的流程编号") from error
    if snapshot is None:
        raise HTTPException(404, "流程不存在")
    scope = _saved_scope(snapshot)
    request.state.audit_workspace_id = scope.workspace_id
    request.state.audit_knowledge_base_id = scope.knowledge_base_id
    _authorize(principal, Action.REVIEW_READ, scope)
    if scope.knowledge_base_id is not None:
        require_knowledge_access(request, principal, scope.knowledge_base_id, Action.KNOWLEDGE_READ)
    return _review_response(thread_id, snapshot)


@router.get("/threads/{thread_id}/content", response_model=ReviewContentResponse)
def get_review_content(thread_id: str, request: Request) -> ReviewContentResponse:
    metadata = get_review_flow(thread_id, request)
    snapshot = _require_checkpoints(request).get(thread_id)
    if snapshot is None or snapshot.answer_result is None:
        raise HTTPException(409, "审核内容尚未就绪")
    return ReviewContentResponse(
        **metadata.model_dump(),
        generation=_generation_report(snapshot.tool_results),
        answer=snapshot.answer_result.text,
        citations=tuple(
            c
            for result in snapshot.tool_results
            if result.document_answer
            for c in result.document_answer.citations
        ),
    )


@router.get("/traces/{request_id}", response_model=ResearchTraceSnapshot)
def get_research_trace(request_id: UUID, request: Request) -> ResearchTraceSnapshot:
    principal = get_current_principal(request)
    store = getattr(request.app.state, "research_trace_store", None)
    if store is None:
        raise HTTPException(503, "研究轨迹存储不可用")
    try:
        snapshot = store.get(request_id)
    except (SQLAlchemyError, ValueError) as error:
        raise HTTPException(503, "研究轨迹查询不可用") from error
    if snapshot is None:
        raise HTTPException(404, "研究轨迹不存在")
    scope = ResourceScope(
        workspace_id=snapshot.workspace_id,
        owner_user_id=snapshot.owner_user_id,
        knowledge_base_id=snapshot.knowledge_base_id,
    )
    _authorize(principal, Action.RESEARCH_READ, scope)
    membership = next(
        item for item in principal.memberships if item.workspace_id == scope.workspace_id
    )
    if principal.user_id != scope.owner_user_id and membership.role not in {
        Role.REVIEWER,
        Role.WORKSPACE_ADMIN,
    }:
        raise HTTPException(403, "无权查看其他研究人员的轨迹")
    if snapshot.knowledge_base_id is not None:
        workspace = require_knowledge_access(
            request, principal, snapshot.knowledge_base_id, Action.KNOWLEDGE_READ
        )
        if workspace != snapshot.workspace_id:
            raise HTTPException(403, "轨迹知识库归属已变化")
    request.state.audit_workspace_id = snapshot.workspace_id
    return snapshot


@router.post("/threads/{thread_id}/review", response_model=ReviewFlowResponse)
def submit_review(thread_id: str, payload: ReviewDecision, request: Request) -> ReviewFlowResponse:
    principal = get_current_principal(request)
    checkpoints = _require_checkpoints(request)
    try:
        snapshot = checkpoints.get(thread_id)
        if snapshot is None:
            raise ReviewNotFoundError(thread_id)
        scope = _saved_scope(snapshot)
        request.state.audit_workspace_id = scope.workspace_id
        request.state.audit_knowledge_base_id = scope.knowledge_base_id
        _authorize(principal, Action.REVIEW_DECIDE, scope)
        if scope.knowledge_base_id is not None:
            require_knowledge_access(request, principal, scope.knowledge_base_id, Action.KNOWLEDGE_READ)
        request.state.research_trace_scope = scope
        run = checkpoints.resume(thread_id, payload)
    except ReviewNotFoundError as error:
        raise HTTPException(404, "流程不存在") from error
    except ReviewConflictError as error:
        raise HTTPException(409, "流程不在待审核状态或已处理") from error
    except ValueError as error:
        raise HTTPException(422, "无效的流程编号") from error
    record_trace(
        TraceKind.REVIEW_COMPLETED,
        review_choice=payload.choice,
        thread_id=UUID(run.thread_id),
    )
    return _review_response(run.thread_id, run.snapshot)
