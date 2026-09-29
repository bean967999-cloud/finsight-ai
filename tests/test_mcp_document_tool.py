"""Day17 Step4: owned, authorized document evidence without invented citations."""

from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType
from finsight.domain.evidence import Citation, EvidenceBundle, EvidenceCandidate, RerankedEvidence
from finsight.domain.mcp_tool_contracts import (
    SearchFinancialDocumentsInput,
    SearchFinancialDocumentsOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
)
from finsight.services.mcp_document_tool import FinancialDocumentTool

WORKSPACE = UUID(int=31)
KNOWLEDGE = UUID(int=32)


class MemoryAudit:
    def __init__(self, *, fail_finish=False) -> None:
        self.events = []
        self.fail_finish = fail_finish

    def begin(self, request_id, *, action, method, route_pattern, target_id) -> None:
        self.events.append(("begin", action, method, route_pattern))

    def finish(self, request_id, *, status_code, actor_user_id=None, workspace_id=None, knowledge_base_id=None) -> None:
        if self.fail_finish:
            raise RuntimeError("private audit error")
        self.events.append(("finish", status_code, workspace_id, knowledge_base_id))


class Ownership:
    def __init__(self, workspace=WORKSPACE) -> None:
        self.workspace = workspace
        self.calls = 0

    def workspace_for(self, knowledge_base_id):
        self.calls += 1
        return self.workspace


class Search:
    def __init__(self, *, empty=False, fail=False, long_excerpt=False) -> None:
        self.calls = 0
        self.criteria = None
        self.empty = empty
        self.fail = fail
        self.long_excerpt = long_excerpt

    def search(self, query, *, criteria=None):
        self.calls += 1
        self.criteria = criteria
        if self.fail:
            raise RuntimeError("private document body must not leak")
        content = "财务披露片段。" * 300 if self.long_excerpt else "2024 年营业收入为 10 亿元。"
        citations = ()
        if not self.empty:
            candidate = EvidenceCandidate(
                vector_id="v1", document_id=1, chunk_id=2, parse_job_id=3,
                chunk_version=1, kind=ChunkKind.TEXT, content=content,
                content_sha256=sha256(content.encode()).hexdigest(), page_start=8, page_end=8,
                source_blocks=(SourceBlockRef(page_number=8, block_index=4),),
                document_title="示例 2024 年报", document_type=DocumentType.ANNUAL_REPORT,
                company_code="DEMO", report_year=2024, retrieval_rank=1, retrieval_score=0.1,
            )
            ranked = RerankedEvidence(
                candidate=candidate, reranker_name="fixture", reranker_version="v1",
                rerank_score=0.9, final_rank=1,
            )
            citations = (Citation(citation_id="C1", evidence=ranked, quoted_text=content),)
        return SimpleNamespace(bundle=EvidenceBundle(
            query_sha256=sha256(query.encode()).hexdigest(),
            candidate_count=0 if self.empty else 1, citations=citations,
        ))


def context(role=Role.RESEARCHER, *, granted=True) -> ToolCallContext:
    return ToolCallContext(
        principal=Principal(user_id=UUID(int=30), memberships=(WorkspaceMembership(
            workspace_id=WORKSPACE, role=role,
            knowledge_base_ids=(KNOWLEDGE,) if granted else (),
        ),)),
        request_id=UUID(int=33),
    )


def payload() -> SearchFinancialDocumentsInput:
    return SearchFinancialDocumentsInput(
        workspace_id=WORKSPACE, knowledge_base_id=KNOWLEDGE,
        query="营业收入是多少", company_code="DEMO",
        document_type="annual_report", report_year=2024,
    )


def test_authorized_search_retains_source_page_pending_status_and_scope() -> None:
    audit, ownership, search = MemoryAudit(), Ownership(), Search()
    result = FinancialDocumentTool(audit, ownership, search).execute(context(), payload())
    assert isinstance(result, SearchFinancialDocumentsOutput)
    assert result.candidate_count == 1
    assert len(result.references) == 1
    reference = result.references[0]
    assert (reference.document_id, reference.chunk_id, reference.page_start) == (1, 2, 8)
    assert reference.citation_status == "pending"
    assert "not verified" in result.limitations[0]
    assert search.criteria.knowledge_base_id == KNOWLEDGE
    assert search.criteria.company_code == "DEMO"
    assert ownership.calls == search.calls == 1
    assert audit.events[1][1] == 200
    assert "营业收入是多少" not in str(audit.events)


def test_permission_and_ownership_fail_before_retrieval() -> None:
    for principal, owner in (
        (context(granted=False), Ownership()),
        (context(Role.WORKSPACE_ADMIN), Ownership(UUID(int=99))),
        (context(), Ownership(None)),
    ):
        search = Search()
        audit = MemoryAudit()
        result = FinancialDocumentTool(audit, owner, search).execute(principal, payload())
        assert isinstance(result, ToolFailure)
        assert result.code == ToolErrorCode.ACCESS_DENIED
        assert search.calls == 0
        assert audit.events[1][1] == 403


def test_empty_result_does_not_invent_evidence_and_failures_are_sanitized() -> None:
    empty = FinancialDocumentTool(MemoryAudit(), Ownership(), Search(empty=True)).execute(
        context(), payload()
    )
    assert isinstance(empty, SearchFinancialDocumentsOutput)
    assert empty.references == () and empty.candidate_count == 0
    assert "No evidence" in empty.limitations[0]

    failed = FinancialDocumentTool(MemoryAudit(), Ownership(), Search(fail=True)).execute(
        context(), payload()
    )
    assert isinstance(failed, ToolFailure)
    assert failed.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert "private" not in failed.model_dump_json()

    hidden = FinancialDocumentTool(
        MemoryAudit(fail_finish=True), Ownership(), Search()
    ).execute(context(), payload())
    assert isinstance(hidden, ToolFailure)
    assert hidden.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert "10 亿元" not in hidden.model_dump_json()


def test_long_excerpt_is_bounded_and_explicitly_marked() -> None:
    result = FinancialDocumentTool(
        MemoryAudit(), Ownership(), Search(long_excerpt=True)
    ).execute(context(), payload())
    assert isinstance(result, SearchFinancialDocumentsOutput)
    assert len(result.references[0].excerpt) == 2000
    assert result.references[0].excerpt_truncated is True
    assert result.references[0].citation_status == "pending"
