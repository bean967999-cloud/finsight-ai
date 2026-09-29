from hashlib import sha256

import pytest
from pydantic import ValidationError

from finsight.domain.document_chunking import SourceBlockRef
from finsight.domain.evidence import (
    Citation,
    CitationStatus,
    EvidenceBundle,
    EvidenceCandidate,
    RerankedEvidence,
)


def candidate(*, chunk_id: int = 7, rank: int = 2) -> EvidenceCandidate:
    content = "2024 年营业收入为 100 亿元，2023 年为 80 亿元。"
    return EvidenceCandidate(
        vector_id=f"chunk-{chunk_id}-v1",
        document_id=3,
        chunk_id=chunk_id,
        parse_job_id=11,
        chunk_version=1,
        kind="text",
        content=content,
        content_sha256=sha256(content.encode()).hexdigest(),
        page_start=2,
        page_end=2,
        section_path=("财务摘要",),
        source_blocks=(SourceBlockRef(page_number=2, block_index=4),),
        document_title="2024 年度报告",
        document_type="annual_report",
        company_code="TEST",
        report_year=2024,
        source_url="https://example.test/report.pdf",
        retrieval_rank=rank,
        retrieval_score=0.032,
    )


def reranked(*, chunk_id: int = 7, final_rank: int = 1) -> RerankedEvidence:
    return RerankedEvidence(
        candidate=candidate(chunk_id=chunk_id),
        reranker_name="test-reranker",
        reranker_version="1",
        rerank_score=0.91,
        final_rank=final_rank,
    )


def test_scores_and_ranks_remain_semantically_separate() -> None:
    result = reranked()
    assert result.candidate.retrieval_rank == 2
    assert result.candidate.retrieval_score == 0.032
    assert result.final_rank == 1
    assert result.rerank_score == 0.91


def test_verified_citation_requires_exact_quote_and_reason() -> None:
    citation = Citation(
        citation_id="C1",
        evidence=reranked(),
        quoted_text="2024 年营业收入为 100 亿元",
        status=CitationStatus.VERIFIED,
        verification_reason="正文、年份和金额与来源块一致",
    )
    assert citation.evidence.candidate.page_start == 2
    with pytest.raises(ValidationError, match="exact substring"):
        Citation(
            citation_id="C1", evidence=reranked(), quoted_text="营业收入为 200 亿元",
        )
    with pytest.raises(ValidationError, match="requires a reason"):
        Citation(
            citation_id="C1", evidence=reranked(), quoted_text="100 亿元",
            status=CitationStatus.VERIFIED,
        )


def test_pending_citation_cannot_claim_verification_reason() -> None:
    with pytest.raises(ValidationError, match="pending citation"):
        Citation(
            citation_id="C1", evidence=reranked(), quoted_text="100 亿元",
            verification_reason="尚未真正校验",
        )


def test_bundle_enforces_order_unique_rank_and_unique_chunk() -> None:
    first = Citation(citation_id="C1", evidence=reranked(), quoted_text="100 亿元")
    second = Citation(
        citation_id="C2", evidence=reranked(chunk_id=8, final_rank=2), quoted_text="80 亿元",
    )
    bundle = EvidenceBundle(query_sha256="a" * 64, candidate_count=5, citations=(first, second))
    assert [item.citation_id for item in bundle.citations] == ["C1", "C2"]
    with pytest.raises(ValidationError, match="citation IDs"):
        EvidenceBundle(
            query_sha256="a" * 64, candidate_count=5,
            citations=(first, second.model_copy(update={"citation_id": "C3"})),
        )
    duplicate = Citation(citation_id="C2", evidence=reranked(final_rank=2), quoted_text="80 亿元")
    with pytest.raises(ValidationError, match="must not appear"):
        EvidenceBundle(
            query_sha256="a" * 64, candidate_count=5, citations=(first, duplicate),
        )
    wrong_rank = Citation(
        citation_id="C2", evidence=reranked(chunk_id=8, final_rank=3), quoted_text="80 亿元",
    )
    with pytest.raises(ValidationError, match="final ranks"):
        EvidenceBundle(
            query_sha256="a" * 64, candidate_count=5, citations=(first, wrong_rank),
        )


def test_candidate_rejects_invalid_page_trace_and_nonfinite_score() -> None:
    with pytest.raises(ValidationError, match="page range"):
        EvidenceCandidate.model_validate(candidate().model_dump() | {"page_start": 1})
    with pytest.raises(ValidationError, match="finite"):
        EvidenceCandidate.model_validate(candidate().model_dump() | {"retrieval_score": float("nan")})
    with pytest.raises(ValidationError, match="content_sha256"):
        EvidenceCandidate.model_validate(candidate().model_dump() | {"content": "正文已变化"})
