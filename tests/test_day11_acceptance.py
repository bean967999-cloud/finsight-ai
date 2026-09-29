"""Offline Day11 scenarios crossing source adapters, review service, and HTTP."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256

from fastapi.testclient import TestClient

from finsight.domain.claim_evidence import ClaimContext, NumericClaim
from finsight.domain.document_chunking import SourceBlockRef
from finsight.domain.evidence import Citation, CitationStatus, EvidenceCandidate, RerankedEvidence
from finsight.domain.query_execution import QueryExecutionResult
from finsight.domain.query_plan import (
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    StructuredQueryPlan,
    TimeSelection,
)
from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.main import app
from finsight.services.evidence_normalization import from_asset_risk, from_citation, from_query_row
from finsight.services.evidence_review import build_review_preview
from finsight.services.risk_analysis import RiskAnalysisService
from finsight.services.risk_recalculation import verify_asset_risk_calculation


def revenue_claim() -> NumericClaim:
    return NumericClaim(
        claim_id="CL1",
        statement="2024 年合并营业收入为 1 亿元",
        context=ClaimContext(
            entity_code="TEST",
            metric_code="revenue",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            currency="CNY",
            consolidation_scope="consolidated",
        ),
        value=Decimal(1),
        unit="亿元",
    )


def verified_quote() -> Citation:
    content = "2024 年收入为 1 亿元，上年收入为 8000 万元。"
    candidate = EvidenceCandidate(
        vector_id="chunk-7-v1",
        document_id=3,
        chunk_id=7,
        parse_job_id=2,
        chunk_version=1,
        kind="text",
        content=content,
        content_sha256=sha256(content.encode()).hexdigest(),
        page_start=4,
        page_end=4,
        source_blocks=(SourceBlockRef(page_number=4, block_index=1),),
        document_title="2024 年年度报告",
        document_type="annual_report",
        company_code="TEST",
        report_year=2024,
        retrieval_rank=1,
        retrieval_score=0.6,
    )
    return Citation(
        citation_id="C1",
        evidence=RerankedEvidence(
            candidate=candidate,
            reranker_name="fixture",
            reranker_version="1",
            rerank_score=0.9,
            final_rank=1,
        ),
        quoted_text="2024 年收入为 1 亿元",
        status=CitationStatus.VERIFIED,
        verification_reason="exact quoted span",
    )


def revenue_rows(
    *amounts: int,
    period_type: str = "annual",
) -> tuple[StructuredQueryPlan, QueryExecutionResult]:
    plan = StructuredQueryPlan(
        query_sha256="a" * 64,
        status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=("TEST",)),
        metrics=(MetricRequest(term="revenue"),),
        time=TimeSelection(report_years=(2024,)),
    )
    rows = tuple(
        {
            "company_code": "TEST",
            "report_date": date(2024, 12, 31),
            "period_type": period_type,
            "item_code": "revenue",
            "value": Decimal(amount),
            "currency": "CNY",
            "unit": "yuan",
            "consolidation_scope": "consolidated",
        }
        for amount in amounts
    )
    result = QueryExecutionResult(
        query_sha256=plan.query_sha256,
        sql_sha256="b" * 64,
        columns=tuple(rows[0]),
        rows=rows,
        row_count=len(rows),
        execution_ms=1,
    )
    return plan, result


def prices() -> PriceSeries:
    return PriceSeries(
        ticker="TEST",
        adjustment_type="forward",
        data_source="fixture",
        data_version=1,
        points=tuple(
            PricePoint(date(2024, 1, 1) + timedelta(days=index), Decimal(100 + index + index % 3))
            for index in range(26)
        ),
    )


def test_document_plus_query_to_http_preview_keeps_quote_unverified_for_amount() -> None:
    target = revenue_claim()
    plan, execution = revenue_rows(100_000_000)
    document = from_citation(verified_quote(), target.context)
    database = from_query_row(
        execution, plan, row_index=0, value_field="value", context=target.context
    )
    response = TestClient(app).post(
        "/api/v1/evidence/review-preview",
        json={
            "claim": target.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in (document, database)],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["pointer"]["kind"] for item in body["review"]["links"]] == [
        "document",
        "query",
    ]
    assert [item["status"] for item in body["numeric_verification"]["checks"]] == [
        "insufficient",
        "supports",
    ]
    assert body["review"]["status"] == "pending"


def test_two_financial_rows_expose_conflict_with_both_row_locations() -> None:
    target = revenue_claim()
    plan, execution = revenue_rows(100_000_000, 120_000_000)
    sources = tuple(
        from_query_row(
            execution, plan, row_index=index, value_field="value", context=target.context
        )
        for index in range(2)
    )
    preview = build_review_preview(target, sources)
    assert preview.numeric_verification is not None
    assert preview.numeric_verification.status == "conflicted"
    assert len(preview.fusion.disagreements) == 1
    assert preview.fusion.disagreements[0].left.row_index == 0
    assert preview.fusion.disagreements[0].right.row_index == 1


def test_quarter_end_cannot_verify_full_year_revenue() -> None:
    target = revenue_claim()
    plan, execution = revenue_rows(100_000_000, period_type="quarterly")
    source = from_query_row(
        execution, plan, row_index=0, value_field="value", context=target.context
    )
    preview = build_review_preview(target, (source,))
    assert preview.numeric_verification is not None
    assert preview.numeric_verification.status == "insufficient"
    assert "period" in preview.fusion.assessments[0].missing_dimensions


def test_risk_recalculation_catches_a_report_that_preview_alone_would_accept() -> None:
    source = prices()
    report = RiskAnalysisService().analyze_asset(source)
    altered = replace(
        report, drawdown=replace(report.drawdown, max_drawdown=report.drawdown.max_drawdown - 0.1)
    )
    target = NumericClaim(
        claim_id="CL2",
        statement="该证券最大回撤为报告所列数值",
        context=ClaimContext(
            entity_code="TEST",
            metric_code="max_drawdown",
            period_start=report.start_date,
            period_end=report.end_date,
            adjustment_type="forward",
        ),
        value=Decimal(str(altered.drawdown.max_drawdown)),
        unit="fraction",
    )
    evidence = from_asset_risk(
        altered,
        source,
        metric_code="max_drawdown",
        context=target.context,
    )
    preview = build_review_preview(target, (evidence,))
    assert preview.numeric_verification is not None
    assert preview.numeric_verification.status == "passed"
    assert preview.review.status == "pending"
    assert verify_asset_risk_calculation(evidence, altered, source).status == "failed"
