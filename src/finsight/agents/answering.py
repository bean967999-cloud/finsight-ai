"""Conservative answer gate: tool success is not a verified financial claim."""

from __future__ import annotations

from finsight.agents.state import ResearchState
from finsight.domain.evidence import CitationStatus
from finsight.domain.research_flow import (
    AnswerStatus,
    ResearchAnswer,
    ResearchIntent,
    ResearchTool,
    ToolStatus,
)
from finsight.services.query_planning import query_digest

_POINTER_KINDS = {
    ResearchTool.DOCUMENT_SEARCH: "document",
    ResearchTool.STRUCTURED_QUERY: "query",
    ResearchTool.RISK_CALCULATION: "risk",
}


def compose_research_answer(state: ResearchState) -> ResearchAnswer:
    if state["classified_intent"] == ResearchIntent.UNSUPPORTED:
        return ResearchAnswer(
            status=AnswerStatus.REFUSED,
            text="当前问题不属于已支持的金融资料、财务数据或风险计算范围。",
            limitations=state.get("plan_limitations") or ("未找到可安全执行的研究工具",),
        )

    plan = state.get("plan_items", ())
    results = state.get("tool_results", ())
    if len(plan) != len(results) or any(
        item.tool != result.tool for item, result in zip(plan, results, strict=True)
    ):
        return _insufficient("工具执行结果与计划不一致，不能形成结论。", "ToolPlanMismatch")

    limitations = list(state.get("plan_limitations", ()))
    for result in results:
        if result.status != ToolStatus.SUCCEEDED:
            limitations.append(f"{result.tool.value}: {result.error_code}")
    if limitations:
        return ResearchAnswer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            text="部分研究步骤未完成，暂不生成金融结论。",
            limitations=tuple(limitations),
        )

    if state["classified_intent"] == ResearchIntent.DOCUMENT and len(results) == 1:
        grounded = results[0].document_answer
        if grounded is not None:
            if grounded.query_sha256 != query_digest(state["query"]) or any(
                citation.status != CitationStatus.VERIFIED for citation in grounded.citations
            ):
                return _insufficient("引用核验不匹配本次问题。", "DocumentAnswerMismatch")
            return ResearchAnswer(status=AnswerStatus.ANSWERED, text=grounded.text)

    evidence = []
    for result in results:
        for item in result.evidence:
            if item.pointer.kind != _POINTER_KINDS[result.tool]:
                return _insufficient("证据来源类型与执行工具不一致。", "EvidenceSourceMismatch")
            evidence.append(item)

    pointers = [item.pointer.model_dump_json() for item in evidence]
    if len(pointers) != len(set(pointers)):
        return _insufficient("发现重复证据引用，不能重复计为独立来源。", "DuplicateEvidence")
    if evidence:
        contexts = {item.context.model_dump_json() for item in evidence}
        if len(contexts) != 1:
            return _insufficient("证据的公司、期间或财务口径不一致。", "EvidenceContextMismatch")
        numeric = [item for item in evidence if item.value is not None]
        if len(numeric) > 1 and len({(item.value, item.unit) for item in numeric}) > 1:
            return _insufficient("同口径证据存在数值或单位分歧，需人工核对。", "EvidenceDisagreement")
        # Normalized facts are still not a verified answer to the user's question.
        return _insufficient(
            f"已取得 {len(evidence)} 条可追溯资料，但尚未完成结论与原始来源的复核。",
            "ClaimReviewPending",
        )

    metrics = state.get("risk_metrics")
    if metrics is not None and state["classified_intent"] == ResearchIntent.RISK:
        return ResearchAnswer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            text=(
                "基于调用方提供的价格序列，已计算基础指标："
                f"累计收益率 {metrics.cumulative_return:.2%}，"
                f"年化波动率 {metrics.annualized_volatility:.2%}，"
                f"最大回撤 {metrics.max_drawdown:.2%}，"
                f"历史 VaR {metrics.historical_var:.2%}，"
                f"历史 CVaR {metrics.historical_cvar:.2%}。"
                "这些数值尚不能作为经核验的投资判断。"
            ),
            limitations=("价格未附证券、交易日期和数据来源；历史风险不保证未来损失",),
        )
    return _insufficient("工具未提供可核验的证据，暂不生成金融结论。", "NoVerifiedEvidence")


def _insufficient(text: str, code: str) -> ResearchAnswer:
    return ResearchAnswer(
        status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        text=text,
        limitations=(code,),
    )
