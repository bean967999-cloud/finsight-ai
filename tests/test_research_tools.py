"""Day13 Step3: planned tools call existing service boundaries, without fake evidence."""

from hashlib import sha256
from uuid import uuid4

from finsight.agents.tools import ResearchToolAdapter
from finsight.domain.query_plan import PlanStatus, QueryIntent
from finsight.domain.research_flow import ResearchPlanItem, ResearchTool, ToolStatus
from finsight.services.query_planning import build_query_plan


class RecordingDocumentSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.output = object()
        self.error: Exception | None = None

    def search(self, query: str, *, criteria=None):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.output


class RecordingStructuredQuery:
    def __init__(self) -> None:
        self.plans = []
        self.output = object()

    def execute(self, plan):
        self.plans.append(plan)
        return self.output


def _item(tool: ResearchTool) -> ResearchPlanItem:
    return ResearchPlanItem(tool=tool, reason="验证工具边界")


def test_document_service_output_is_preserved_but_not_prematurely_verified() -> None:
    search = RecordingDocumentSearch()
    adapter = ResearchToolAdapter(document_search=search)
    result = adapter.execute(
        _item(ResearchTool.DOCUMENT_SEARCH), query="查年报原文", knowledge_base_id=uuid4()
    )
    assert search.queries == ["查年报原文"]
    assert result.result.status == ToolStatus.SUCCEEDED
    assert result.output is search.output
    assert result.result.evidence == ()


def test_document_unavailable_and_invalid_query_have_different_statuses() -> None:
    search = RecordingDocumentSearch()
    adapter = ResearchToolAdapter(document_search=search)
    search.error = ConnectionError("network detail must not leak")
    unavailable = adapter.search_documents("查年报", knowledge_base_id=uuid4())
    assert unavailable.result.status == ToolStatus.UNAVAILABLE
    assert unavailable.result.error_code == "DocumentSearchUnavailable"
    assert unavailable.output is None
    search.error = ValueError("bad query")
    invalid = adapter.search_documents("查年报", knowledge_base_id=uuid4())
    assert invalid.result.status == ToolStatus.FAILED
    assert invalid.result.error_code == "InvalidDocumentQuery"


def test_structured_query_requires_ready_matching_plan() -> None:
    service = RecordingStructuredQuery()
    adapter = ResearchToolAdapter(structured_query=service)
    query = "查找证券信息"
    item = _item(ResearchTool.STRUCTURED_QUERY)
    missing = adapter.execute(item, query=query)
    assert missing.result.error_code == "StructuredPlanRequired"
    wrong = build_query_plan("另一个问题", status=PlanStatus.READY, intent=QueryIntent.COMPANY_LOOKUP)
    mismatch = adapter.execute(item, query=query, structured_plan=wrong)
    assert mismatch.result.status == ToolStatus.FAILED
    assert mismatch.result.error_code == "QueryPlanMismatch"
    plan = build_query_plan(query, status=PlanStatus.READY, intent=QueryIntent.COMPANY_LOOKUP)
    good = adapter.execute(item, query=query, structured_plan=plan)
    assert good.result.status == ToolStatus.SUCCEEDED
    assert good.output is service.output
    assert good.result.evidence == ()
    assert service.plans == [plan]


def test_risk_adapter_calls_existing_calculator_without_claiming_price_provenance() -> None:
    result = ResearchToolAdapter().execute(
        _item(ResearchTool.RISK_CALCULATION),
        query="计算价格波动率",
        prices=(100.0, 105.0, 102.0, 110.0),
    )
    assert result.result.status == ToolStatus.SUCCEEDED
    assert result.output is not None
    assert result.output.observations == 4
    assert result.result.evidence == ()
    missing = ResearchToolAdapter().calculate_risk(None)
    assert missing.result.error_code == "PricesRequired"
    invalid = ResearchToolAdapter().calculate_risk((100.0, 0.0, 101.0))
    assert invalid.result.status == ToolStatus.FAILED


def test_plan_digest_is_tied_to_exact_question_text() -> None:
    query = "查找证券信息"
    plan = build_query_plan(query, status=PlanStatus.READY, intent=QueryIntent.COMPANY_LOOKUP)
    assert plan.query_sha256 == sha256(query.encode("utf-8")).hexdigest()
    assert plan.query_sha256 != sha256("查找其他证券".encode()).hexdigest()
