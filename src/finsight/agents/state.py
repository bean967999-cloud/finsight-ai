from typing import TypedDict

from finsight.domain.query_plan import StructuredQueryPlan
from finsight.domain.research_flow import (
    ResearchAnswer,
    ResearchIntent,
    ResearchPlanItem,
    ResearchToolResult,
    ToolOutputSummary,
)
from finsight.domain.schemas import RiskMetrics


class ResearchState(TypedDict, total=False):
    query: str
    workspace_id: str
    knowledge_base_id: str
    owner_user_id: str
    release_requested: bool
    review_request: dict[str, object]
    review_outcome: dict[str, str]
    prices: list[float]
    structured_plan: StructuredQueryPlan

    intent: str
    plan: list[str]

    rag_evidence: list[str]
    sql_evidence: list[str]
    risk_metrics: RiskMetrics

    final_answer: str
    verification_notes: list[str]

    # Day13 structured contract. Old fields remain until graph nodes migrate.
    plan_items: tuple[ResearchPlanItem, ...]
    plan_limitations: tuple[str, ...]
    classified_intent: ResearchIntent
    tool_results: tuple[ResearchToolResult, ...]
    output_summaries: tuple[ToolOutputSummary, ...]
    answer_result: ResearchAnswer
