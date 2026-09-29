from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType
from finsight.services.document_retrieval import RetrievedChunk
from finsight.services.evidence_reranking import EvidenceRerankingService


class FakeReranker:
    name = "test-reranker"
    version = "fixture-v1"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def score(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        self.calls.append((query, passages))
        return tuple(self.scores[passage] for passage in passages)


def chunk(chunk_id: int, content: str, retrieval_score: float, *, document_id: int = 1):
    return RetrievedChunk(
        vector_id=f"vector-{chunk_id}", document_id=document_id, chunk_id=chunk_id,
        parse_job_id=document_id, chunk_version=1, kind=ChunkKind.TEXT, content=content,
        page_start=chunk_id, page_end=chunk_id,
        section_path=("经营情况",),
        source_blocks=(SourceBlockRef(page_number=chunk_id, block_index=0),),
        document_title="示例公司 2024 年报", document_type=DocumentType.ANNUAL_REPORT,
        company_code="DEMO", report_year=2024, source_url=None, score=retrieval_score,
    )


def test_independent_score_reorders_retrieval_candidates() -> None:
    first = chunk(1, "公司营业收入为100亿元。", 0.09)
    second = chunk(2, "公司归母净利润为20亿元。", 0.03)
    model = FakeReranker({first.content: 0.15, second.content: 0.92})

    result = EvidenceRerankingService(model, candidate_top_k=2, final_top_n=2).rerank(
        "归母净利润是多少", (first, second),
    )

    assert [item.candidate.chunk_id for item in result.evidence] == [2, 1]
    assert [item.final_rank for item in result.evidence] == [1, 2]
    assert result.evidence[0].candidate.retrieval_rank == 2
    assert result.evidence[0].candidate.retrieval_score == 0.03
    assert result.evidence[0].rerank_score == 0.92


def test_top_k_is_applied_before_scoring_and_exact_duplicates_are_removed() -> None:
    first = chunk(1, "营业收入为100亿元。", 0.3)
    duplicate = chunk(2, first.content, 0.2)
    outside_top_k = chunk(3, "不应进入模型。", 0.1)
    model = FakeReranker({first.content: 0.8})

    result = EvidenceRerankingService(model, candidate_top_k=2, final_top_n=1).rerank(
        "营业收入", (first, duplicate, outside_top_k),
    )

    assert model.calls == [("营业收入", (first.content,))]
    assert result.trace.input_count == 3
    assert result.trace.duplicate_chunk_ids == (2,)
    assert result.trace.scored_chunk_ids == (1,)


def test_near_duplicate_from_same_document_is_suppressed_after_scoring() -> None:
    base = "公司营业收入为100亿元，同比增长10%，主要来自主营业务。"
    overlap = "公司营业收入为100亿元，同比增长10%，主要来自主营业务和海外市场。"
    other = "公司经营现金流净额为30亿元。"
    candidates = (chunk(1, base, 0.3), chunk(2, overlap, 0.2), chunk(3, other, 0.1))
    model = FakeReranker({base: 0.99, overlap: 0.98, other: 0.70})

    result = EvidenceRerankingService(
        model, candidate_top_k=3, final_top_n=2, redundancy_threshold=0.65,
    ).rerank("营业收入和现金流", candidates)

    assert result.trace.selected_chunk_ids == (1, 3)
    assert result.trace.redundant_chunk_ids == (2,)


def test_equal_scores_use_original_retrieval_order() -> None:
    first = chunk(1, "第一段", 0.3)
    second = chunk(2, "第二段", 0.2)
    model = FakeReranker({first.content: 0.5, second.content: 0.5})
    result = EvidenceRerankingService(model, candidate_top_k=2, final_top_n=2).rerank(
        "问题", (first, second),
    )
    assert result.trace.selected_chunk_ids == (1, 2)
