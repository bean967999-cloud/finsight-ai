import { TechnicalDetails, TechnicalValue, ErrorNotice } from "../Presentation/TechnicalDetails";
import { label, explanation } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useCallback, useEffect, useState } from "react";
import { rate, evaluatedCount, type EvaluationOverview } from "../Api/Evaluation";
import { useSession } from "../Auth/Session";
import { TrustNotice } from "../Presentation/TrustNotice";
import { requestFailure } from "../Api/Client";

export function EvaluationPage() {
  const { request } = useSession();
  const [overview, setOverview] = usePageState<EvaluationOverview | null>("EvaluationPage.overview", null);
  const [error, setError] = usePageState("EvaluationPage.error", "");
  const [busy, setBusy] = useState(false);
  const [knowledgeBaseId, setKnowledgeBaseId] = usePageState("EvaluationPage.knowledgeBaseId", "");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setOverview(await request<EvaluationOverview>("/api/v1/evaluation/overview", "GET"));
    } catch (failure) {
      setOverview(null);
      setError(requestFailure(failure, "评估摘要读取失败。"));
    } finally {
      setBusy(false);
    }
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  const research = overview?.research;
  const retrieval = overview?.retrieval;
  const toolPassed = research?.tool_cases.filter((item) => item.passed).length ?? 0;
  const numericPassed = research?.numeric_cases.filter((item) => item.passed).length ?? 0;

  return <div className="evaluation-layout">
    <section className="page-card evaluation-head">
      <h1>评估看板</h1>
      <TrustNotice summary="合成题按本次请求重算；真实文档区展示已保存的观察评分。两类结果分别计分，不代表生产表现。" title="评估来源与样本边界">
        <p>重新计算本地题集会重算合成题；运行真实公告题集才会发起新的文档检索评估。读取页面不等于重跑真实题集。</p>
        <p>题目数量不等于独立事实数量；同一事实的不同问法不能推广为金融领域准确率。当前看板不是外部生成模型的全面效果评测。</p>
      </TrustNotice>
      <button type="button" onClick={() => void load()} disabled={busy}>
        {busy ? "正在计算…" : "重新计算本地题集"}
      </button>
      {error && <ErrorNotice message={error} />}
      {overview && <p className="muted">题集 {research?.suite_name} {research?.suite_version}
        · 生成时间 {new Date(overview.generated_at).toLocaleString("zh-CN")}
        · 来源：固定合成题，当次重算</p>}
    </section>

    {research && <section className="page-card evaluation-section">
      <h2>工具选择与数值一致性</h2>
      <p className="muted">数据来源：{label("source", research.source)}。只证明固定样例上的规划与公式，不代表真实投研完成率。</p>
      <div className="metric-grid">
        <div><span>工具题整题通过</span><strong>{evaluatedCount(toolPassed, research.metrics.tool_case_count)}</strong></div>
        <div><span>意图准确率</span><strong>{rate(research.metrics.intent_accuracy)}</strong></div>
        <div><span>工具集合准确率</span><strong>{rate(research.metrics.tool_set_accuracy)}</strong></div>
        <div><span>限制识别准确率</span><strong>{rate(research.metrics.limitation_accuracy)}</strong></div>
        <div><span>数值题整题通过</span><strong>{evaluatedCount(numericPassed, research.metrics.numeric_case_count)}</strong></div>
        <div><span>数值指标通过率</span><strong>{rate(research.metrics.numeric_metric_pass_rate)}</strong></div>
      </div>
      <h3>逐题记录</h3>
      <div className="case-grid">
        {research.tool_cases.map((item) => <article key={item.case_id}>
          <strong>{item.case_id} · {item.passed ? "通过" : "未通过"}</strong>
          <p>意图 {item.intent_correct ? "正确" : "错误"} · 工具集合 {item.tool_set_correct ? "正确" : "错误"}
            · 限制识别 {item.limitation_correct ? "正确" : "错误"}</p>
          {item.failure_reasons.length > 0 && <p>原因：{item.failure_reasons.map(explanation).join("、")}</p>}
        </article>)}
        {research.numeric_cases.map((item) => <article key={item.case_id}>
          <strong>{item.case_id} · {item.passed ? "通过" : "未通过"}</strong>
          <p>{item.metrics.filter((metric) => metric.passed).length} / {item.metrics.length} 个指标通过</p>
          {item.metrics.filter((metric) => !metric.passed).map((metric) =>
            <p key={label("metric", metric.metric)}>{label("metric", metric.metric)}：{metric.failure_reason ? explanation(metric.failure_reason) : "未通过"}；
              期望 {metric.expected}，观察 {metric.observed ?? "缺失"}，容差 {metric.absolute_tolerance}</p>)}
        </article>)}
      </div>
    </section>}

    {retrieval && <section className="page-card evaluation-section">
      <h2>文档检索与引用评估</h2>
      <TrustNotice summary="真实文档评估只证明固定版本题集和所列来源的表现，不是开放问题准确率。" title="检索指标解释">
        <p>Recall@K衡量前K个检索候选覆盖目标证据的情况；重排命中@N衡量目标证据是否进入重排后的前N个结果。</p>
        <p>引用正确率与拒答准确率按题集规则评分；未运行和缺失结果不计作通过。</p>
      </TrustNotice>
      <label>真实评估知识库编号<input value={knowledgeBaseId} onChange={e => setKnowledgeBaseId(e.target.value.trim())} /></label>
      <button disabled={busy || !knowledgeBaseId} onClick={() => {
        setBusy(true); setError("");
        void request("/api/v1/evaluation/retrieval-runs", "POST", { knowledge_base_id: knowledgeBaseId })
          .then(() => load()).catch(failure => {
            setError(requestFailure(failure, "真实评估失败。")); setBusy(false);
          });
      }}>{busy ? "正在运行或读取评估…" : "运行真实公告题集"}</button>
      {overview?.retrieval_run && <><p>真实评估时间：{overview.retrieval_run.executed_at} · 来源：{label("source", overview.retrieval_run.source)}</p>
        <TechnicalDetails><TechnicalValue name="评估运行编号" value={overview.retrieval_run.run_id} /><TechnicalValue name="知识库编号" value={overview.retrieval_run.knowledge_base_id} /></TechnicalDetails></>}
      <p>固定小样本的原文锚定核验，不是开放问题正确率或财务审计意见；合成题与真实文档题分别计分。</p>
      <p className="muted">同一来源事实可以有不同问法，题目数量不等于独立事实数量。缺失资料、筛选冲突和能力边界分别设计拒答题。</p>
      <p className="muted">题集 {retrieval.dataset_name} {retrieval.dataset_version} · 状态 {label("evaluation", retrieval.status)}</p>
      {retrieval.status === "not_run" ? <>
        <p className="result-status">尚未运行真实文档评估，不显示 Recall、重排命中或引用正确率。</p>
        <p>未运行题号：{retrieval.unrun_question_ids.join("、")}</p>
        <p className="muted">需要取得原始 PDF、核实页码与知识库归属，并保存完整检索观察结果后才能评分。</p>
      </> : retrieval.metrics ? <div className="metric-grid">
        <div><span>Recall@K</span><strong>{rate(retrieval.metrics.retrieval_recall_at_k)}</strong></div>
        <div><span>重排命中@N</span><strong>{rate(retrieval.metrics.rerank_hit_rate_at_n)}</strong></div>
        <div><span>引用正确率</span><strong>{rate(retrieval.metrics.citation_correctness)}</strong></div>
        <div><span>拒答准确率</span><strong>{rate(retrieval.metrics.refusal_accuracy)}</strong></div>
      </div> : <p className="error">评估状态与指标不一致，暂不展示成绩。</p>}
      {retrieval.status === "observations_scored" && retrieval.metrics && <>
        <p>真实题数：{retrieval.metrics.question_count} · 可回答：{retrieval.metrics.answerable_count}
          · 应拒答：{retrieval.metrics.refusal_count}</p>
        <p>当次平均耗时：{retrieval.metrics.mean_latency_ms.toFixed(2)} ms；不是生产压测结果。</p>
        {retrieval.cases && <>
          <h3>真实题逐题结果</h3>
          <p>整题通过：{retrieval.cases.filter(c => c.passed).length} / {retrieval.cases.length}</p>
          <div className="case-grid">{retrieval.cases.map(c => <article key={c.question_id}>
            <strong>{c.question_id} · {c.passed ? "通过" : "未通过"}</strong>
            <p>预期：{c.should_refuse ? "拒答" : "有来源回答"} · 实际：{c.refused ? "拒答" : "回答"}</p>
            <p>检索排名：{c.retrieval_rank ?? "未命中"} · 重排排名：{c.rerank_rank ?? "未命中"}
              · 引用匹配：{c.citation_correct ? "通过" : "未通过或不适用"}</p>
            {c.failure_reasons.length > 0 && <p>失败原因：{c.failure_reasons.map(explanation).join("、")}</p>}
          </article>)}</div>
        </>}
      </>}
    </section>}
  </div>;
}
