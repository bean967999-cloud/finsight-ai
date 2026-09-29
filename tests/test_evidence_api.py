from hashlib import sha256

from fastapi.testclient import TestClient

from finsight.api.routes.evidence import get_evidence_search
from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType
from finsight.domain.evidence import Citation, EvidenceBundle, EvidenceCandidate, RerankedEvidence
from finsight.main import app
from finsight.services.document_retrieval import RetrievalTrace
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.evidence_reranking import RerankingTrace
from finsight.services.evidence_search import EvidenceSearchResult


class FakeEvidenceSearch:
    def __init__(self) -> None:
        self.criteria: DocumentSearchFilter | None = None

    def search(
        self, query: str, *, criteria: DocumentSearchFilter | None = None,
    ) -> EvidenceSearchResult:
        self.criteria = criteria
        content = "2024年公司营业收入为10亿元。"
        candidate = EvidenceCandidate(
            vector_id="vector-1", document_id=1, chunk_id=2, parse_job_id=3,
            chunk_version=1, kind=ChunkKind.TEXT, content=content,
            content_sha256=sha256(content.encode()).hexdigest(), page_start=8, page_end=8,
            source_blocks=(SourceBlockRef(page_number=8, block_index=4),),
            document_title="示例公司2024年年报", document_type=DocumentType.ANNUAL_REPORT,
            company_code="DEMO", report_year=2024, source_url="https://example.test/report.pdf",
            retrieval_rank=2, retrieval_score=0.03,
        )
        ranked = RerankedEvidence(
            candidate=candidate, reranker_name="fixture", reranker_version="v1",
            rerank_score=0.91, final_rank=1,
        )
        return EvidenceSearchResult(
            bundle=EvidenceBundle(
                query_sha256=sha256(query.strip().encode()).hexdigest(), candidate_count=2,
                citations=(Citation(citation_id="C1", evidence=ranked, quoted_text=content),),
            ),
            retrieval_trace=RetrievalTrace(
                model_name="BAAI/bge-m3", query_token_count=8, filtered_document_ids=(1,),
                candidate_vector_ids=("vector-1", "vector-2"), accepted_chunk_ids=(2,),
                rejected_hits=(),
            ),
            reranking_trace=RerankingTrace(
                input_count=2, candidate_count=2, scored_chunk_ids=(2, 3),
                selected_chunk_ids=(2,), duplicate_chunk_ids=(), redundant_chunk_ids=(3,),
            ),
        )


def test_evidence_endpoint_returns_pending_traceable_sources(agent_auth) -> None:
    fake = FakeEvidenceSearch()
    app.dependency_overrides[get_evidence_search] = lambda: fake
    try:
        response = TestClient(app).post("/api/v1/evidence/search", headers=agent_auth.headers(), json={
            "query": "营业收入是多少",
            "knowledge_base_id": str(agent_auth.knowledge_base_id),
            "company_code": "DEMO",
            "document_type": "annual_report",
            "report_year": 2024,
        })
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    citation = body["bundle"]["citations"][0]
    assert citation["citation_id"] == "C1"
    assert citation["status"] == "pending"
    assert citation["evidence"]["candidate"]["page_start"] == 8
    assert citation["evidence"]["candidate"]["source_blocks"] == [
        {"page_number": 8, "block_index": 4},
    ]
    assert body["retrieval"]["rejected_hit_count"] == 0
    assert body["reranking"]["redundant_chunk_ids"] == [3]
    assert "营业收入是多少" not in response.text
    assert fake.criteria == DocumentSearchFilter(
        company_code="DEMO", document_type=DocumentType.ANNUAL_REPORT, report_year=2024,
        knowledge_base_id=agent_auth.knowledge_base_id,
    )


def test_unconfigured_endpoint_is_explicitly_unavailable(agent_auth) -> None:
    response = TestClient(app).post(
        "/api/v1/evidence/search", headers=agent_auth.headers(),
        json={"query": "营业收入是多少", "knowledge_base_id": str(agent_auth.knowledge_base_id)},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "evidence search is not configured on this process"


def test_request_contract_rejects_invalid_query_and_year() -> None:
    app.dependency_overrides[get_evidence_search] = lambda: FakeEvidenceSearch()
    try:
        response = TestClient(app).post(
            "/api/v1/evidence/search", json={"query": " ", "report_year": 1800},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
