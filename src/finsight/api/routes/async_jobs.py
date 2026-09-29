"""Submit a durable job and inspect its current database-backed state."""

import base64
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from finsight.api.knowledge_access import require_knowledge_access
from finsight.api.routes.auth import get_current_principal
from finsight.domain.access_control import Action
from finsight.domain.async_job import AsyncJobSnapshot, AsyncJobSubmission
from finsight.infrastructure.database.session import SessionFactory
from finsight.services.async_job_reader import AsyncJobReader
from finsight.services.async_job_submission import (
    AsyncJobConflict,
    AsyncJobSubmissionService,
    AsyncJobTargetError,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class DocumentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    knowledge_base_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    company_code: str | None = Field(default=None, max_length=32)
    report_year: int = Field(ge=1900, le=2100)
    source_url: str | None = Field(default=None, max_length=2000)
    # Bounded JSON transfer for small disclosure PDFs; not a large-file uploader.
    pdf_base64: str = Field(min_length=8, max_length=5_592_408)


@router.get("/documents")
def list_documents(knowledge_base_id: UUID, request: Request):
    from finsight.infrastructure.database.models import Document, DocumentParseJob
    from finsight.infrastructure.database.models.knowledge_base import KnowledgeBaseDocument

    require_knowledge_access(request, get_current_principal(request), knowledge_base_id, Action.KNOWLEDGE_READ)
    with SessionFactory() as session:
        rows = session.scalars(select(Document).join(
            KnowledgeBaseDocument, KnowledgeBaseDocument.document_id == Document.id
        ).where(KnowledgeBaseDocument.knowledge_base_id == knowledge_base_id).order_by(Document.id).limit(100))
        result = []
        for row in rows:
            parsed = session.scalars(select(DocumentParseJob).where(
                DocumentParseJob.document_id == row.id
            ).order_by(DocumentParseJob.id.desc()).limit(1)).first()
            result.append({"document_id": row.id, "title": row.title, "report_year": row.report_year,
                           "company_code": row.company_code, "source_url": row.source_url,
                           "parse_job_id": parsed.id if parsed else None,
                           "parse_status": parsed.status.value if parsed else None})
        return {"documents": result, "limit": 100}


@router.post("/documents/upload", status_code=201)
def upload_document(payload: DocumentUploadRequest, request: Request):
    from finsight.core.config import get_settings
    from finsight.domain.document_data import DocumentType
    from finsight.infrastructure.database.models import Document, DocumentIngestionJob
    from finsight.infrastructure.database.models.knowledge_base import KnowledgeBaseDocument
    from finsight.infrastructure.storage.local import LocalObjectStorage
    from finsight.services.document_ingestion import (
        DocumentIngestionError,
        DocumentIngestionService,
    )

    require_knowledge_access(request, get_current_principal(request), payload.knowledge_base_id, Action.KNOWLEDGE_MANAGE)
    try:
        content = base64.b64decode(payload.pdf_base64, validate=True)
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:] or not 0 < len(content) <= 4 * 1024 * 1024:
            raise ValueError("invalid PDF size or signature")
    except Exception as exc:
        raise HTTPException(422, "仅支持4MB以内且包含PDF头尾标记的文件") from exc
    digest = sha256(content).hexdigest()
    with SessionFactory() as session:
        existing = session.scalar(select(Document).where(Document.content_sha256 == digest))
        if existing is not None:
            association = session.get(KnowledgeBaseDocument, (payload.knowledge_base_id, existing.id))
            # No cross-knowledge-base deduplication may grant access implicitly.
            if association is None:
                raise HTTPException(409, "文件不能自动关联到此知识库，请由管理员核对归属")
            if any((existing.title != payload.title, existing.company_code != payload.company_code,
                    existing.report_year != payload.report_year, existing.source_url != payload.source_url,
                    existing.document_type != DocumentType.ANNOUNCEMENT)):
                raise HTTPException(409, "相同文件的元数据不一致，不能静默覆盖")
    try:
        job_id = DocumentIngestionService(SessionFactory, LocalObjectStorage(get_settings().object_storage_root)).ingest(
            content, idempotency_key=f"{payload.knowledge_base_id}:{payload.idempotency_key}",
            title=payload.title, document_type=DocumentType.ANNOUNCEMENT,
            company_code=payload.company_code, report_year=payload.report_year, source_url=payload.source_url,
            allowed_existing_document_ids=frozenset({existing.id}) if existing else frozenset(),
        )
    except DocumentIngestionError as exc:
        raise HTTPException(409, "登记冲突或失败，请查询后重试") from exc
    with SessionFactory() as session, session.begin():
        job = session.get(DocumentIngestionJob, job_id)
        if session.get(KnowledgeBaseDocument, (payload.knowledge_base_id, job.document_id)) is None:
            session.add(KnowledgeBaseDocument(knowledge_base_id=payload.knowledge_base_id, document_id=job.document_id))
        return {"document_id": job.document_id, "ingestion_job_id": job_id,
                "content_sha256": digest, "parse_started": False}


class ChunkPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_base_id: UUID
    parse_job_id: int = Field(gt=0)


@router.post("/documents/chunks")
def prepare_chunks(payload: ChunkPreparationRequest, request: Request):
    from finsight.core.config import get_settings
    from finsight.domain.document_data import DocumentParseStatus
    from finsight.infrastructure.database.models import DocumentParseJob
    from finsight.infrastructure.database.models.knowledge_base import KnowledgeBaseDocument
    from finsight.infrastructure.storage.local import LocalObjectStorage
    from finsight.services.document_chunk_persistence import (
        ChunkPersistenceError,
        DocumentChunkPersistenceService,
    )
    from finsight.services.document_chunk_quality import audit_chunks
    from finsight.services.document_chunk_source import ChunkSourceLoader
    from finsight.services.financial_chunker import FinancialTextChunker

    require_knowledge_access(request, get_current_principal(request), payload.knowledge_base_id, Action.KNOWLEDGE_MANAGE)
    with SessionFactory() as session:
        parsed = session.get(DocumentParseJob, payload.parse_job_id)
        if parsed is None or session.get(KnowledgeBaseDocument, (payload.knowledge_base_id, parsed.document_id)) is None:
            raise HTTPException(422, "解析任务不属于此知识库")
        if parsed.status != DocumentParseStatus.SUCCEEDED:
            raise HTTPException(422, "解析未成功，不能生成切块")
    source = ChunkSourceLoader(SessionFactory, LocalObjectStorage(get_settings().object_storage_root)).load(payload.parse_job_id)
    drafts = FinancialTextChunker().chunk(source)
    quality = audit_chunks(source, drafts)
    if not quality.passed or quality.block_coverage_ratio != 1:
        raise HTTPException(422, "切块质量校验未通过")
    try:
        chunks = DocumentChunkPersistenceService(SessionFactory).save(source, drafts)
    except ChunkPersistenceError as exc:
        raise HTTPException(409, "已有切块版本存在冲突") from exc
    return {"parse_job_id": payload.parse_job_id, "chunk_count": len(chunks), "chunk_version": 1,
            "coverage": quality.block_coverage_ratio}


class JobSubmissionResponse(BaseModel):
    job: AsyncJobSnapshot
    replayed: bool


def get_submission_service() -> AsyncJobSubmissionService:
    return AsyncJobSubmissionService(SessionFactory)


def get_job_reader() -> AsyncJobReader:
    return AsyncJobReader(SessionFactory)


@router.post("", response_model=JobSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_job(
    payload: AsyncJobSubmission,
    request: Request,
    response: Response,
    service: Annotated[AsyncJobSubmissionService, Depends(get_submission_service)],
) -> JobSubmissionResponse:
    principal = get_current_principal(request)
    if payload.knowledge_base_id is None:
        raise HTTPException(422, "文档任务必须指定知识库编号")
    require_knowledge_access(
        request, principal, payload.knowledge_base_id, Action.KNOWLEDGE_MANAGE
    )
    try:
        result = service.submit(payload)
    except AsyncJobConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AsyncJobTargetError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/jobs/{result.job.job_id}"
    return JobSubmissionResponse(job=result.job, replayed=result.replayed)


@router.get("/{job_id}", response_model=AsyncJobSnapshot)
def get_job(
    job_id: int,
    request: Request,
    reader: Annotated[AsyncJobReader, Depends(get_job_reader)],
) -> AsyncJobSnapshot:
    principal = get_current_principal(request)
    if job_id < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid job ID")
    job = reader.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if job.knowledge_base_id is None:
        raise HTTPException(403, "旧任务缺少知识库归属，不能直接授权")
    require_knowledge_access(request, principal, job.knowledge_base_id, Action.KNOWLEDGE_READ)
    return job
