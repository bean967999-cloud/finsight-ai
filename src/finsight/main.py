import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from finsight.agents.checkpoints import (
    ResearchCheckpointService,
    make_research_saver,
    project_checkpoint_connection,
)
from finsight.agents.graph import build_research_graph
from finsight.agents.tools import ResearchToolAdapter
from finsight.api.routes.admin import router as admin_router
from finsight.api.routes.agent import router as agent_router
from finsight.api.routes.async_jobs import router as async_jobs_router
from finsight.api.routes.auth import router as auth_router
from finsight.api.routes.evaluation import router as evaluation_router
from finsight.api.routes.evidence import router as evidence_router
from finsight.api.routes.evidence_review import router as evidence_review_router
from finsight.api.routes.health import router as health_router
from finsight.api.routes.risk import router as risk_router
from finsight.api.routes.risk_report import router as risk_report_router
from finsight.api.routes.structured_query import router as structured_query_router
from finsight.core.config import get_settings
from finsight.infrastructure.database.session import SessionFactory
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.knowledge_scope import KnowledgeScopeService
from finsight.services.market_price_reader import MarketPriceReader
from finsight.services.operation_audit import OperationAuditService, audit_target
from finsight.services.read_only_query_executor import ReadOnlyQueryExecutor
from finsight.services.research_trace_store import CaptureTraceSink, ResearchTraceStore
from finsight.services.structured_query import StructuredQueryService
from finsight.services.structured_trace import (
    JsonLogTraceSink,
    TraceKind,
    configure_trace_logging,
    record_trace,
    trace_request,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.startup_complete = False
    configure_trace_logging()
    auth_secret = settings.auth_jwt_secret.get_secret_value()
    auth_tokens = (
        TokenCodec(auth_secret, ttl_minutes=settings.auth_token_minutes) if auth_secret else None
    )
    with project_checkpoint_connection(settings.database_url) as connection:
        saver = make_research_saver(connection)
        saver.setup()
        application.state.research_checkpoints = ResearchCheckpointService(
            saver,
            ResearchToolAdapter(
                structured_query=application.state.structured_query,
                document_search=getattr(application.state, "evidence_search", None),
                document_answer=getattr(application.state, "document_answer", None),
            ),
            database_url=settings.database_url,
        )
        if auth_tokens is not None:
            application.state.auth_service = AuthenticationService(
                IdentityService(SessionFactory),
                auth_tokens,
            )
        application.state.audit_service = OperationAuditService(SessionFactory)
        application.state.research_trace_store = ResearchTraceStore(SessionFactory)
        try:
            application.state.startup_complete = True
            yield
        finally:
            application.state.startup_complete = False
            del application.state.research_checkpoints
            del application.state.audit_service
            del application.state.research_trace_store
            if hasattr(application.state, "auth_service"):
                del application.state.auth_service


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Enterprise Financial Research & Risk Intelligence Copilot",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_identity_and_audit(request: Request, call_next):
    started = perf_counter()
    request_id = uuid4()
    request.state.request_id = request_id
    target = audit_target(request.method, request.url.path)
    audit = getattr(request.app.state, "audit_service", None)
    sink = CaptureTraceSink(getattr(request.app.state, "trace_sink", None))

    async def complete(response):
        response.headers["X-Request-ID"] = str(request_id)
        route = request.scope.get("route")
        route_pattern = target[1] if target is not None else getattr(route, "path", "unmatched")
        record_trace(
            TraceKind.HTTP_COMPLETED,
            route_pattern=route_pattern,
            method=request.method,
            status_code=response.status_code,
            duration_ms=(perf_counter() - started) * 1000,
        )
        scope = getattr(request.state, "research_trace_scope", None)
        if scope is not None:
            store = getattr(request.app.state, "research_trace_store", None)
            response.headers["X-Trace-Status"] = "unavailable"
            if store is not None:
                try:
                    await run_in_threadpool(store.save, request_id, scope, sink)
                    response.headers["X-Trace-Status"] = "stored"
                except Exception:  # noqa: BLE001 - diagnostics must not change a business result
                    logging.getLogger("finsight.structured_trace").warning(
                        "research trace persistence failed for request %s", request_id
                    )
        return response

    with trace_request(request_id, sink):
        if target is not None and audit is not None:
            try:
                await run_in_threadpool(
                    audit.begin, request_id, action=target[0], method=request.method,
                    route_pattern=target[1], target_id=target[2],
                )
            except (SQLAlchemyError, OSError, RuntimeError):
                return await complete(
                    JSONResponse(status_code=503, content={"detail": "操作审计不可用"})
                )
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - retain the request ID on unhandled failures
            # Never log exception text, request bodies or locals: dependency errors may
            # contain connection strings. Frames and type are enough to locate a fault.
            frames = []
            traceback = exc.__traceback__
            while traceback is not None:
                code = traceback.tb_frame.f_code
                frames.append(f"{code.co_name}:{traceback.tb_lineno}")
                traceback = traceback.tb_next
            logging.getLogger("finsight.request_error").error(
                "request=%s error_type=%s frames=%s", request_id, type(exc).__name__, frames
            )
            if target is not None and audit is not None:
                try:
                    await run_in_threadpool(
                        audit.finish, request_id, status_code=500,
                        actor_user_id=getattr(request.state, "audit_actor_id", None),
                        workspace_id=getattr(request.state, "audit_workspace_id", None),
                        knowledge_base_id=getattr(request.state, "audit_knowledge_base_id", None),
                    )
                except (SQLAlchemyError, OSError, RuntimeError):
                    return await complete(JSONResponse(
                        status_code=503, content={"detail": "操作审计未能完成"}
                    ))
            return await complete(JSONResponse(status_code=500, content={"detail": "请求处理失败"}))
        if target is not None and audit is not None:
            try:
                await run_in_threadpool(
                    audit.finish, request_id, status_code=response.status_code,
                    actor_user_id=getattr(request.state, "audit_actor_id", None),
                    workspace_id=getattr(request.state, "audit_workspace_id", None),
                    knowledge_base_id=getattr(request.state, "audit_knowledge_base_id", None),
                )
            except (SQLAlchemyError, OSError, RuntimeError):
                return await complete(JSONResponse(
                    status_code=503, content={"detail": "操作审计未能完成"}
                ))
        return await complete(response)


app.state.structured_query = StructuredQueryService(ReadOnlyQueryExecutor(SessionFactory))
app.state.market_price_reader = MarketPriceReader(SessionFactory)
app.state.knowledge_scope = KnowledgeScopeService(SessionFactory)
app.state.trace_sink = JsonLogTraceSink()
app.state.research_graph = build_research_graph(
    ResearchToolAdapter(structured_query=app.state.structured_query)
)

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(async_jobs_router)
app.include_router(risk_router)
app.include_router(risk_report_router)
app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(evidence_router)
app.include_router(evidence_review_router)
app.include_router(evaluation_router)
app.include_router(structured_query_router)
