from dataclasses import dataclass

from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType
from finsight.services.document_retrieval import RetrievalResult, RetrievalTrace, RetrievedChunk
from finsight.services.evidence_reranking import EvidenceRerankingService
from finsight.services.evidence_search import EvidenceSearchService


class FakeRetrieval:
    def __init__(self, chunks: tuple[RetrievedChunk, ...]) -> None:
        self.chunks = chunks
        self.limit: int | None = None

    def retrieve(self, query: str, *, criteria=None, limit: int = 5) -> RetrievalResult:
        self.limit = limit
        return RetrievalResult(
            self.chunks,
            RetrievalTrace("embedding-fixture", 6, None, ("v1",), (1,), ()),
        )


@dataclass
class FakeReranker:
    name: str = "reranker-fixture"
    version: str = "v1"

    def score(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        return tuple(float(index) for index in range(len(passages), 0, -1))


def test_search_composes_retrieval_reranking_and_pending_citations() -> None:
    content = "营业收入为10亿元。"
    retrieved = RetrievedChunk(
        vector_id="v1", document_id=1, chunk_id=1, parse_job_id=1, chunk_version=1,
        kind=ChunkKind.TEXT, content=content, page_start=1, page_end=1,
        section_path=("经营情况",),
        source_blocks=(SourceBlockRef(page_number=1, block_index=0),),
        document_title="示例年报", document_type=DocumentType.ANNUAL_REPORT,
        company_code="DEMO", report_year=2024, source_url=None, score=0.03,
    )
    retrieval = FakeRetrieval((retrieved,))
    service = EvidenceSearchService(
        retrieval,  # type: ignore[arg-type]
        EvidenceRerankingService(FakeReranker(), candidate_top_k=7, final_top_n=3),
    )

    result = service.search(" 营业收入是多少 ")

    assert retrieval.limit == 7
    assert result.bundle.candidate_count == 1
    assert result.bundle.citations[0].status.value == "pending"
    assert result.bundle.citations[0].quoted_text == content
    assert result.bundle.query_sha256 != "营业收入是多少"
