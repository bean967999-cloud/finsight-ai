from hashlib import sha256

from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType
from finsight.domain.evidence import CitationStatus, EvidenceCandidate, RerankedEvidence
from finsight.services.citation_verification import CitationVerifier


def evidence(content: str) -> RerankedEvidence:
    candidate = EvidenceCandidate(
        vector_id="vector-1", document_id=1, chunk_id=1, parse_job_id=1,
        chunk_version=1, kind=ChunkKind.TEXT, content=content,
        content_sha256=sha256(content.encode()).hexdigest(), page_start=8, page_end=8,
        source_blocks=(SourceBlockRef(page_number=8, block_index=2),),
        document_title="示例公司2024年年报", document_type=DocumentType.ANNUAL_REPORT,
        company_code="DEMO", report_year=2024, retrieval_rank=2, retrieval_score=0.03,
    )
    return RerankedEvidence(
        candidate=candidate, reranker_name="fixture", reranker_version="v1",
        rerank_score=0.91, final_rank=1,
    )


def test_matching_amount_percentage_and_year_are_verified() -> None:
    source = "2024年，公司营业收入为10亿元，同比增长12.5%。"
    result = CitationVerifier().verify(
        citation_id="C1", evidence=evidence(source),
        claim_text="2024年营业收入为10亿元，同比增长12.5% [C1]。",
        quoted_text=source,
    )
    assert result.citation.status == CitationStatus.VERIFIED
    assert result.unsupported_facts == ()
    assert [fact.canonical for fact in result.claim_facts] == [
        "year:2024", "currency_cny:1E+9", "percent:12.5",
    ]


def test_equivalent_currency_scales_are_normalized() -> None:
    source = "本期研发投入为10,000万元。"
    result = CitationVerifier().verify(
        citation_id="C1", evidence=evidence(source),
        claim_text="研发投入为1亿元。", quoted_text=source,
    )
    assert result.citation.status == CitationStatus.VERIFIED


def test_wrong_value_or_unit_is_rejected_with_auditable_details() -> None:
    source = "毛利率同比提升2个百分点，达到30%。"
    result = CitationVerifier().verify(
        citation_id="C1", evidence=evidence(source),
        claim_text="毛利率同比提升2%，达到35%。", quoted_text=source,
    )
    assert result.citation.status == CitationStatus.REJECTED
    assert [fact.raw for fact in result.unsupported_facts] == ["2%", "35%"]
    assert "2%" in (result.citation.verification_reason or "")


def test_citation_marker_number_is_not_treated_as_financial_fact() -> None:
    source = "公司经营活动现金流保持稳定。"
    result = CitationVerifier().verify(
        citation_id="C1", evidence=evidence(source),
        claim_text="经营活动现金流保持稳定 [C1]。", quoted_text=source,
    )
    assert result.citation.status == CitationStatus.VERIFIED
    assert result.claim_facts == ()


def test_non_source_quote_is_returned_as_rejected_not_raised() -> None:
    source = "营业收入为10亿元。"
    result = CitationVerifier().verify(
        citation_id="C1", evidence=evidence(source),
        claim_text="营业收入为20亿元。", quoted_text="营业收入为20亿元。",
    )
    assert result.citation.status == CitationStatus.REJECTED
    assert "not an exact substring" in (result.citation.verification_reason or "")
    assert result.citation.quoted_text == source
