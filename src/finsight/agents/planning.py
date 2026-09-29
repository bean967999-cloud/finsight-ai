"""Deterministic intent signals and an inspectable research plan."""

from __future__ import annotations

import re
from dataclasses import dataclass

from finsight.domain.research_flow import (
    ResearchIntent,
    ResearchPlanItem,
    ResearchQuestion,
    ResearchTool,
)

DOCUMENT_TERMS = (
    "年报", "季报", "财报", "公告", "披露", "原文", "文档", "页码", "章节", "研报"
)
STRUCTURED_TERMS = (
    "营收", "营业收入", "净利润", "利润率", "现金流", "资产负债", "同比", "环比",
    "财务数据", "财务指标", "市值", "估值", "收入"
)
RISK_TERMS = (
    "波动率", "回撤", "夏普", "风险计算", "风险分析", "组合风险", "收益率",
    "在险价值", "预期损失", "beta", "drawdown", "volatility", "sharpe"
)
_RISK_WORDS = re.compile(
    r"(?<![A-Za-z])(?:c?var|beta|drawdown|volatility|sharpe)(?![A-Za-z])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    intent: ResearchIntent
    items: tuple[ResearchPlanItem, ...]
    limitations: tuple[str, ...] = ()


def plan_research(question: ResearchQuestion) -> ResearchPlan:
    """Select candidate tools; never interpret a keyword hit as retrieved evidence."""
    query = question.query.casefold()
    wants_document = any(term in query for term in DOCUMENT_TERMS)
    wants_structured = any(term in query for term in STRUCTURED_TERMS)
    # An explicitly bounded announcement fact does not request a second database tool.
    if "根据公告" in query and any(term in query for term in ("股息", "非利息收入增", "平均生息资产")) and not any(
        term in query for term in ("数据库", "结构化", "sql", "对比", "比对")
    ):
        wants_structured = False
    wants_risk = (
        any(term in query for term in RISK_TERMS)
        or bool(_RISK_WORDS.search(query))
        or ("风险" in query and not wants_document)
    )

    requested = sum((wants_document, wants_structured, wants_risk))
    if requested == 0:
        return ResearchPlan(
            ResearchIntent.UNSUPPORTED,
            (),
            ("当前仅支持财务文档、结构化财务数据和价格风险问题",),
        )

    intent = (
        ResearchIntent.MIXED
        if requested > 1
        else ResearchIntent.DOCUMENT if wants_document
        else ResearchIntent.STRUCTURED if wants_structured
        else ResearchIntent.RISK
    )
    items: list[ResearchPlanItem] = []
    limitations: list[str] = []
    if wants_document:
        items.append(
            ResearchPlanItem(tool=ResearchTool.DOCUMENT_SEARCH, reason="定位文档原文和页码证据")
        )
    if wants_structured:
        items.append(
            ResearchPlanItem(tool=ResearchTool.STRUCTURED_QUERY, reason="核对结构化财务口径与期间")
        )
    if wants_risk:
        items.append(
            ResearchPlanItem(tool=ResearchTool.RISK_CALCULATION, reason="用价格序列确定性计算风险指标")
        )
        if question.prices is None:
            limitations.append("风险计算缺少价格序列，不能凭问题文字生成指标")
    return ResearchPlan(intent, tuple(items), tuple(limitations))
