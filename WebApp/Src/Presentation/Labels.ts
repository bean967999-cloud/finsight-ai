// Display-only translations: never use these labels to authorize or submit requests.
const dictionaries = {
  role: { viewer: "只读成员", researcher: "研究员", reviewer: "审核员", workspace_admin: "工作空间管理员" },
  intent: { document_research: "文档研究", structured_query: "结构化查询", risk_analysis: "风险分析", mixed_research: "综合研究", unsupported: "不支持的研究类型" },
  tool: { document_search: "文档检索", structured_query: "结构化查询", risk_calculation: "风险计算" },
  toolStatus: { succeeded: "执行成功", unavailable: "暂不可用", failed: "执行失败" },
  answer: { answered: "已回答", insufficient_evidence: "证据不足", refused: "已拒答" },
  phase: { submitted: "已提交", planned: "已规划", tools_complete: "工具执行结束", awaiting_review: "等待人工审核", finished: "流程已结束" },
  review: { confirmed: "已确认", rejected: "已驳回" },
  citation: { pending: "待核验 · 不能视为结论依据", verified: "原文锚定已核验", rejected: "核验未通过" },
  job: { pending: "等待调度", queued: "已排队", running: "执行中", retry_wait: "等待重试", succeeded: "执行成功", failed: "执行失败" },
  event: { http_completed: "接口请求结束", research_plan: "研究规划", tool_completed: "工具执行结束", research_completed: "研究处理结束", review_completed: "人工审核处理结束" },
  evaluation: { not_run: "尚未运行", observations_scored: "已对观察结果评分" },
  source: { synthetic_fixture: "固定合成样例", external_document_required: "需要外部文档", local_synthetic_recomputed_on_request: "本次请求重算合成题集", real_local_pdf_retrieval_and_source_anchoring: "本地真实PDF检索与原文锚定", real_document_retrieval: "真实文档检索", eastmoney_public: "东方财富公开行情" },
  adjustment: { none: "未复权", qfq: "前复权", hfq: "后复权" },
  metric: { cumulative_return: "累计收益率", annualized_volatility: "年化波动率", max_drawdown: "最大回撤", historical_var: "历史VaR", historical_cvar: "历史CVaR", sharpe_ratio: "夏普比率" },
  action: {
    research_submit: "提交研究", evidence_search: "检索证据", review_read: "读取审核摘要",
    review_content_read: "读取审核正文", review_decide: "作出审核决定", auth_login: "登录",
    workspace_audit_read: "读取工作空间审计", research_trace_read: "读取研究轨迹",
    document_job_submit: "提交文档任务", document_job_read: "读取文档任务",
    scoped_document_list: "读取授权文档列表", scoped_document_upload: "登记授权文档", scoped_chunk_prepare: "生成文档切块",
    risk_calculate: "计算基础风险", risk_asset_report: "计算单资产报告", risk_portfolio_report: "计算组合报告",
    public_asset_risk_read: "读取公共行情并计算单资产风险", public_portfolio_risk_read: "读取公共行情并计算组合风险",
    evaluation_overview_read: "读取评估摘要", real_document_evaluation_run: "运行真实文档题集",
  },
} satisfies Record<string, Record<string, string>>;

export type LabelCategory = keyof typeof dictionaries;
export function label(category: LabelCategory, value: string | null | undefined): string {
  if (value == null || value === "") return "未记录";
  return (dictionaries[category] as Record<string, string>)[value] ?? `未识别状态（${value}）`;
}

const explanations: Record<string, string> = {
  "Trading-calendar gaps have not been verified.": "尚未核验交易日历，无法确认价格数据是否缺少应有的交易日。",
  "Historical risk estimates do not bound future losses.": "历史风险估计不代表未来损失上限。",
  "Beta was not calculated because no benchmark was supplied.": "未提供基准资产，因此未计算Beta（相对基准的收益敏感度）。",
  "Prices and source labels were supplied by the caller and have not been verified.": "价格与来源标识由调用方提供，尚未独立核验。",
  "Currency compatibility has not been verified.": "尚未核验各资产的币种是否一致或可比较。",
  "Target weights are restored each observed period; trading costs are excluded.": "计算假设每个观察期恢复目标权重，未计入交易成本。",
  "The current query does not apply a cross-source or revision-priority policy.": "查询尚未自动选择跨来源或修订版本优先级；同一指标存在多个版本时，本页面拒绝展示，请先核对来源。",
  "quote is source-anchored and every claim number matches in value and unit": "引用原句已定位到来源片段，结论中的数值与单位核验一致。",
  "quote is source-anchored; no numeric claim required numeric comparison": "引用原句已定位到来源片段，本次未涉及需要比较的数值主张。",
  "requested quote is not an exact substring of the source chunk": "所请求的引用原句与来源片段不完全匹配，核验未通过。",
  expected_refusal_missing: "应拒答但未拒答", retrieval_miss: "检索未命中", rerank_miss: "重排未命中",
  citation_not_supported: "引用缺少来源支持", unexpected_refusal: "非预期拒答",
  missing_metric: "指标缺失", non_finite_metric: "指标不是有限数值", outside_tolerance: "超出允许容差",
  intent_mismatch: "研究意图不匹配", tool_set_mismatch: "工具集合不匹配", limitation_mismatch: "限制识别不匹配",
  ToolPlanMismatch: "工具执行结果与研究计划不一致", DocumentAnswerMismatch: "文档回答与本次问题或引用核验不匹配",
  EvidenceSourceMismatch: "证据来源类型与工具不一致", DuplicateEvidence: "存在重复证据",
  EvidenceContextMismatch: "证据公司、期间或口径不一致", EvidenceDisagreement: "证据数值或单位存在分歧",
  ClaimReviewPending: "结论与原始来源尚待复核", NoVerifiedEvidence: "没有可核验的证据",
  UnexpectedToolError: "工具执行异常，未形成合格结果",
  KnowledgeBaseScopeRequired: "需要指定有权限的知识库范围", DocumentSearchNotConfigured: "文档检索服务尚未配置",
  DocumentSearchUnavailable: "文档检索服务暂不可用", InvalidDocumentQuery: "文档检索条件无效",
  StructuredPlanRequired: "需要有效的结构化查询计划", QueryPlanMismatch: "查询计划与本次问题不匹配",
  StructuredQueryNotConfigured: "结构化查询服务尚未配置", StructuredQueryUnavailable: "结构化查询服务暂不可用",
  InvalidStructuredQuery: "结构化查询条件无效", PricesRequired: "缺少价格序列", InvalidPriceSeries: "价格序列无效",
};

export function explanation(value: string | null | undefined): string {
  if (value == null || value === "") return "未提供说明";
  if (explanations[value]) return explanations[value];
  const numericPrefix = "claim numbers or units are not supported by the quote: ";
  if (value.startsWith(numericPrefix)) return `结论中的部分数值或单位缺少该引用支持：${value.slice(numericPrefix.length)}`;
  const toolFailure = /^(document_search|structured_query|risk_calculation): (\w+)$/.exec(value);
  if (toolFailure) return `${label("tool", toolFailure[1])}：${explanation(toolFailure[2])}`;
  // Preserve an unknown explanation instead of silently suppressing a limitation.
  return /[\u3400-\u9fff]/.test(value) ? value : `尚未映射的说明：${value}`;
}

export function booleanLabel(value: boolean | null | undefined): string {
  return value == null ? "未记录" : value ? "是" : "否";
}
