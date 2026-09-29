from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from finsight.domain.claim_evidence import ClaimContext
from finsight.domain.document_chunking import SourceBlockRef
from finsight.domain.evidence import Citation, CitationStatus, EvidenceCandidate, RerankedEvidence
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
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
from finsight.services.evidence_normalization import (
    EvidenceNormalizationError,
    from_asset_risk,
    from_citation,
    from_portfolio_risk,
    from_query_row,
)
from finsight.services.portfolio_risk import PortfolioPosition
from finsight.services.risk_analysis import RiskAnalysisService


def context(**updates: object) -> ClaimContext:
    fields = {
        "entity_code": "TEST",
        "metric_code": "revenue",
        "period_start": date(2024, 1, 1),
        "period_end": date(2024, 12, 31),
        "currency": "CNY",
        "consolidation_scope": "consolidated",
    }
    fields.update(updates)
    return ClaimContext(**fields)


def citation(status: CitationStatus = CitationStatus.VERIFIED) -> Citation:
    content = "2024 年收入 100 亿元；2023 年收入 80 亿元。"
    candidate = EvidenceCandidate(
        vector_id="v1",
        document_id=3,
        chunk_id=7,
        parse_job_id=1,
        chunk_version=2,
        kind="text",
        content=content,
        content_sha256=sha256(content.encode()).hexdigest(),
        page_start=2,
        page_end=2,
        source_blocks=(SourceBlockRef(page_number=2, block_index=0),),
        document_title="2024 年报",
        document_type="annual_report",
        company_code="TEST",
        report_year=2024,
        retrieval_rank=1,
        retrieval_score=0.5,
    )
    return Citation(
        citation_id="C1",
        evidence=RerankedEvidence(
            candidate=candidate,
            reranker_name="test",
            reranker_version="1",
            rerank_score=0.8,
            final_rank=1,
        ),
        quoted_text="2023 年收入 80 亿元",
        status=status,
        verification_reason="exact source quote" if status != CitationStatus.PENDING else None,
    )


def financial_query() -> tuple[StructuredQueryPlan, QueryExecutionResult]:
    plan = StructuredQueryPlan(
        query_sha256="a" * 64,
        status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=("TEST",)),
        metrics=(MetricRequest(term="revenue"),),
        time=TimeSelection(report_years=(2024,)),
    )
    row = {
        "company_code": "TEST",
        "report_date": date(2024, 12, 31),
        "period_type": "annual",
        "item_code": "revenue",
        "value": Decimal(10000000000),
        "currency": "CNY",
        "unit": "yuan",
        "consolidation_scope": "consolidated",
    }
    result = QueryExecutionResult(
        query_sha256=plan.query_sha256,
        sql_sha256="b" * 64,
        columns=tuple(row),
        rows=(row,),
        row_count=1,
        execution_ms=1,
    )
    return plan, result


def prices(ticker: str = "TEST", multiplier: int = 1) -> PriceSeries:
    return PriceSeries(
        ticker=ticker,
        adjustment_type="forward",
        data_source="fixture",
        data_version=1,
        points=tuple(
            PricePoint(
                date(2024, 1, 1) + timedelta(days=index),
                Decimal(100 + index + index % 3) * multiplier,
            )
            for index in range(25)
        ),
    )


def test_document_quote_keeps_pointer_but_does_not_infer_period_or_value() -> None:
    fact = from_citation(citation(), context())
    assert fact.pointer.kind == "document"
    assert fact.pointer.chunk_version == 2
    assert fact.value is None
    assert fact.grounded_dimensions == (EvidenceDimension.ENTITY,)
    with pytest.raises(EvidenceNormalizationError, match="verified"):
        from_citation(citation(CitationStatus.REJECTED), context())
    with pytest.raises(EvidenceNormalizationError, match="company"):
        from_citation(citation(), context(entity_code="OTHER"))


def test_financial_row_has_exact_locator_and_grounded_accounting_dimensions() -> None:
    plan, result = financial_query()
    fact = from_query_row(result, plan, row_index=0, value_field="value", context=context())
    assert fact.value == Decimal(10000000000)
    assert fact.unit == "yuan"
    assert fact.pointer.row_index == 0
    assert len(fact.pointer.row_sha256) == 64
    assert {
        EvidenceDimension.PERIOD,
        EvidenceDimension.CURRENCY,
        EvidenceDimension.CONSOLIDATION_SCOPE,
    } <= set(fact.grounded_dimensions)


def test_query_rejects_mismatched_plan_row_and_missing_value() -> None:
    plan, result = financial_query()
    wrong_plan = plan.model_copy(update={"query_sha256": "c" * 64})
    with pytest.raises(EvidenceNormalizationError, match="digests"):
        from_query_row(result, wrong_plan, row_index=0, value_field="value", context=context())
    with pytest.raises(EvidenceNormalizationError, match="currency"):
        from_query_row(
            result, plan, row_index=0, value_field="value", context=context(currency="USD")
        )
    empty_row = dict(result.rows[0], value=None)
    empty_result = result.model_copy(update={"rows": (empty_row,)})
    with pytest.raises(EvidenceNormalizationError, match="numeric"):
        from_query_row(empty_result, plan, row_index=0, value_field="value", context=context())


def test_market_row_does_not_claim_adjustment_was_verified() -> None:
    plan = StructuredQueryPlan(
        query_sha256="a" * 64,
        status=PlanStatus.READY,
        intent=QueryIntent.MARKET_PRICE,
        entities=EntitySelection(tickers=("TEST",)),
        metrics=(MetricRequest(term="close_price"),),
        time=TimeSelection(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31)),
    )
    row = {"ticker": "TEST", "currency": "CNY", "average_close_price": Decimal("101.2")}
    result = QueryExecutionResult(
        query_sha256=plan.query_sha256,
        sql_sha256="b" * 64,
        columns=tuple(row),
        rows=(row,),
        row_count=1,
        execution_ms=1,
    )
    claim_context = context(
        entity_code="TEST",
        metric_code="close_price",
        period_end=date(2024, 1, 31),
        adjustment_type="forward",
        consolidation_scope=None,
    )
    fact = from_query_row(
        result, plan, row_index=0, value_field="average_close_price", context=claim_context
    )
    assert EvidenceDimension.ADJUSTMENT_TYPE not in fact.grounded_dimensions
    assert fact.unit == "CNY"


def test_asset_risk_value_and_source_digest_are_extracted() -> None:
    source = prices()
    report = RiskAnalysisService().analyze_asset(source)
    claim_context = context(
        metric_code="max_drawdown",
        period_start=report.start_date,
        period_end=report.end_date,
        currency=None,
        consolidation_scope=None,
        adjustment_type="forward",
    )
    fact = from_asset_risk(report, source, metric_code="max_drawdown", context=claim_context)
    assert fact.value == Decimal(str(report.drawdown.max_drawdown))
    assert fact.unit == "fraction"
    assert fact.pointer.kind == "risk"
    assert len(fact.pointer.input_sha256) == 64
    with pytest.raises(EvidenceNormalizationError, match="provenance"):
        from_asset_risk(report, prices("OTHER"), metric_code="max_drawdown", context=claim_context)


def test_portfolio_subject_is_not_falsely_grounded_by_a_caller_label() -> None:
    positions = (PortfolioPosition(prices("AAA"), 0.6), PortfolioPosition(prices("BBB", 2), 0.4))
    report = RiskAnalysisService().analyze_portfolio(positions)
    first, last = report.portfolio.returns[0], report.portfolio.returns[-1]
    claim_context = context(
        entity_code="my-portfolio",
        metric_code="annualized_volatility",
        period_start=first.period_start,
        period_end=last.period_end,
        currency=None,
        consolidation_scope=None,
        adjustment_type="forward",
    )
    fact = from_portfolio_risk(
        report, positions, metric_code="annualized_volatility", context=claim_context
    )
    assert fact.unit == "fraction"
    assert EvidenceDimension.ENTITY not in fact.grounded_dimensions
    assert fact.pointer.subject_key == "my-portfolio"


def test_normalized_numeric_evidence_requires_unit() -> None:
    fact = from_citation(citation(), context())
    with pytest.raises(ValidationError, match="both value and unit"):
        NormalizedEvidence(
            pointer=fact.pointer, context=fact.context, source_text="100", value=Decimal(100)
        )
