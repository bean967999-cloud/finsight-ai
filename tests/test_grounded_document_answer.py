from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest

from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.evidence import Citation, CitationStatus, EvidenceCandidate, RerankedEvidence
from finsight.services.grounded_document_answer import GroundedDocumentAnswerService, requested_fact


@pytest.mark.parametrize("amount", ["6.50", "7.25"])
def test_annual_total_variant_extracts_source_value_and_excludes_interim(amount):
    from finsight.services.grounded_document_answer import extract_quote

    content = (
        "Fourth interim dividend of HK$3.20 per share; "
        f"total dividends of HK${amount} per share for 2023 (HK$4.10 per share in 2022)."
    )
    quote = extract_quote("dividend", content, year=2023)
    assert quote is not None and amount in quote and "3.20" not in quote
    assert extract_quote("dividend", content, year=2022) is None


def test_comparative_year_in_original_variant_does_not_match_requested_year():
    from finsight.services.grounded_document_answer import extract_quote

    content = "Total dividend distribution for 2023 was HK$6.50 per share (2022: HK$4.10)."
    assert extract_quote("dividend", content, year=2024) is None
    assert extract_quote("dividend", content, year=2022) is None


def test_interim_only_and_conflicting_annual_totals_refuse():
    from finsight.services.grounded_document_answer import extract_quote

    assert extract_quote("dividend", "Fourth interim dividend of HK$3.20 per share for 2023", year=2023) is None
    assert extract_quote("dividend", (
        "total dividends of HK$6.50 per share for 2023. "
        "total dividends of HK$9.99 per share for 2023."
    ), year=2023) is None


def test_new_annual_total_variant_passes_service_verification():
    citation = candidate("total dividends of HK$6.50 per share for 2023 (HK$4.10 per share in 2022)")
    citation = citation.model_copy(update={"evidence": citation.evidence.model_copy(update={
        "candidate": citation.evidence.candidate.model_copy(update={"report_year": 2023, "document_title": "Hang Seng 2023 results"})
    })})
    search = SimpleNamespace(search=lambda *args, **kwargs: SimpleNamespace(bundle=SimpleNamespace(citations=(citation,))))
    service = GroundedDocumentAnswerService(search, None, None)
    service._anchored = lambda c: True
    answer = service.answer("根据公告，恒生银行2023年每股全年股息是多少？", uuid4())
    assert answer is not None and "6.50" in answer.text
    assert answer.citations[0].status == CitationStatus.VERIFIED


def candidate(content):
    row = EvidenceCandidate(
        vector_id="v1",
        document_id=1,
        chunk_id=1,
        parse_job_id=1,
        chunk_version=1,
        kind=ChunkKind.TEXT,
        content=content,
        content_sha256=sha256(content.encode()).hexdigest(),
        page_start=1,
        page_end=1,
        source_blocks=(SourceBlockRef(page_number=1, block_index=0),),
        document_title="Hang Seng 2024 results",
        document_type="announcement",
        report_year=2024,
        retrieval_rank=1,
        retrieval_score=1,
    )
    ranked = RerankedEvidence(
        candidate=row, reranker_name="test", reranker_version="v1", rerank_score=1, final_rank=1
    )
    return Citation(citation_id="C1", evidence=ranked, quoted_text=content)


@pytest.mark.parametrize(
    "query",
    [
        "股息是多少",
        "2024与2023年股息",
        "2024年股息与非利息收入增幅",
        "2024年非利息收入总额",
        "2024年风险如何",
        "2023年第四次中期股息是多少",
        "What was the fourth interim dividend for 2023?",
        "根据公告，2024年股息率是多少？",
        "根据公告，预计2024年未来每股股息是多少？",
    ],
)
def test_ambiguous_or_unsupported_question_refuses(query):
    assert requested_fact(query) is None


def test_value_is_extracted_not_hardcoded_and_year_filter_is_applied():
    citation = candidate(
        "Total dividend distribution for 2024 was HK$9.15 per share, an improvement of 1% year-on-year."
    )
    criteria_seen = []

    class Search:
        def search(self, query, *, criteria):
            criteria_seen.append(criteria)
            return SimpleNamespace(bundle=SimpleNamespace(citations=(citation,)))

    service = GroundedDocumentAnswerService(Search(), None, None)
    service._anchored = lambda c: True
    answer = service.answer("2024年股息是多少？", uuid4())
    assert answer is not None and "9.15" in answer.text and "6.80" not in answer.text
    assert answer.citations[0].status == CitationStatus.VERIFIED
    assert criteria_seen[0].report_year == 2024


def test_source_mismatch_refuses_instead_of_marking_verified():
    citation = candidate(
        "Total dividend distribution for 2024 was HK$9.15 per share, an improvement of 1% year-on-year."
    )
    search = SimpleNamespace(
        search=lambda *args, **kwargs: SimpleNamespace(
            bundle=SimpleNamespace(citations=(citation,))
        )
    )
    service = GroundedDocumentAnswerService(search, None, None)
    service._anchored = lambda c: False
    assert service.answer("2024年股息是多少？", uuid4()) is None


def test_other_bank_or_wrong_source_year_refuses():
    citation = candidate(
        "Total dividend distribution for 2023 was HK$9.15 per share, an improvement of 1% year-on-year."
    )
    search = SimpleNamespace(
        search=lambda *args, **kwargs: SimpleNamespace(
            bundle=SimpleNamespace(citations=(citation,))
        )
    )
    service = GroundedDocumentAnswerService(search, None, None)
    service._anchored = lambda c: True
    assert service.answer("2024年股息是多少？", uuid4()) is None


def test_missing_authoritative_chunk_refuses():
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args):
            return None

    service = GroundedDocumentAnswerService(None, Session, None)
    assert not service._anchored(candidate("sample").evidence.candidate)


def test_explicit_announcement_fact_does_not_need_database_but_comparison_does():
    from finsight.agents.planning import plan_research
    from finsight.domain.research_flow import ResearchQuestion, ResearchTool

    single = plan_research(ResearchQuestion(query="根据公告，2024年非利息收入增幅是多少？"))
    assert tuple(item.tool for item in single.items) == (ResearchTool.DOCUMENT_SEARCH,)
    mixed = plan_research(ResearchQuestion(query="根据公告，2024年非利息收入增幅是多少？并与数据库比对"))
    assert {item.tool for item in mixed.items} == {ResearchTool.DOCUMENT_SEARCH, ResearchTool.STRUCTURED_QUERY}


def test_explicit_filter_is_preserved_and_conflicting_year_or_scope_refuses():
    from finsight.services.document_search_filter import DocumentSearchFilter

    calls = []
    class Search:
        def search(self, query, *, criteria):
            calls.append(criteria)
            return SimpleNamespace(bundle=SimpleNamespace(citations=()))

    kb = uuid4()
    service = GroundedDocumentAnswerService(Search(), None, None)
    filters = DocumentSearchFilter(knowledge_base_id=kb, company_code="NO_SUCH_COMPANY", document_type="annual_report", report_year=2024)
    assert service.answer("2024年股息是多少？", kb, criteria=filters) is None
    assert calls == [filters]
    for criteria in (filters.model_copy(update={"report_year":2023}), filters.model_copy(update={"knowledge_base_id":uuid4()})):
        assert service.answer("2024年股息是多少？", kb, criteria=criteria) is None
    assert len(calls) == 1
