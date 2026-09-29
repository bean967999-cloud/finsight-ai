import { label, booleanLabel } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useEvidenceRun } from "../Auth/EvidenceRun";
import { useSession } from "../Auth/Session";
import type { ResearchTraceSnapshot } from "../Api/Trace";
import { requestFailure } from "../Api/Client";
import { TechnicalDetails, TechnicalValue, ErrorNotice } from "../Presentation/TechnicalDetails";

function ids(values: number[]): string {
  return values.length ? values.join("、") : "无";
}

export function TracePage() {
  const { run } = useEvidenceRun();
  const { request } = useSession();
  const [params] = useSearchParams();
  const [requestId, setRequestId] = usePageState(`TracePage.requestId:${params.get("requestId") ?? "default"}`, params.get("requestId") ?? "");
  const [snapshot, setSnapshot] = usePageState<ResearchTraceSnapshot | null>(`TracePage.snapshot:${params.get("requestId") ?? "default"}`, null);
  const [error, setError] = usePageState(`TracePage.error:${params.get("requestId") ?? "default"}`, "");
  const [busy, setBusy] = useState(false);

  async function load() {
    setSnapshot(null); setError("");
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requestId)) {
      setError("请填写有效的请求 UUID。"); return;
    }
    setBusy(true);
    try {
      setSnapshot(await request<ResearchTraceSnapshot>(`/api/v1/agent/traces/${requestId}`, "GET"));
    } catch (failure) {
      setError(requestFailure(failure, "轨迹查询失败。"));
    } finally { setBusy(false); }
  }
  return <section className="page-card trace-page">
    <span className="status-pill">研究轨迹与文档检索轨迹</span>
    <h1>执行轨迹</h1>
    <h2>已存储的单次研究请求</h2>
    <div className="audit-controls"><label>研究请求编号<input value={requestId} disabled={busy}
      onChange={(event) => setRequestId(event.target.value.trim())} /></label>
      <button type="button" disabled={busy} onClick={() => void load()}>{busy ? "正在查询…" : "查询研究轨迹"}</button></div>
    {error && <ErrorNotice message={error} />}
    {snapshot && <>
      <TechnicalDetails><TechnicalValue name="研究请求编号" value={snapshot.request_id} /><TechnicalValue name="工作空间编号" value={snapshot.workspace_id} /><TechnicalValue name="研究人编号" value={snapshot.owner_user_id} /><TechnicalValue name="知识库编号" value={snapshot.knowledge_base_id} /></TechnicalDetails>
      {snapshot.truncated && <p className="error">事件超过存储上限，轨迹已截断，不能视为完整。</p>}
      <ol>{snapshot.frames.map((frame) => <li key={frame.sequence}>
        <strong>{label("event", frame.event.kind)}</strong> · {frame.occurred_at}
        {frame.event.intent && <p>意图 {label("intent", frame.event.intent)} · 计划工具 {frame.event.planned_tools.map(tool => label("tool", tool)).join("、")}</p>}
        {frame.event.tool && <p>工具 {label("tool", frame.event.tool)} · {label("toolStatus", frame.event.tool_status)} · 耗时 {frame.event.duration_ms?.toFixed(2) ?? "未记录"} ms</p>}
        {frame.event.error_code && <p className="error">本步骤存在异常，请展开诊断信息核查。</p>}
        {frame.event.answer_status && <p>回答状态：{label("answer", frame.event.answer_status)} · 待审核：{booleanLabel(frame.event.review_pending)}</p>}
        {(frame.event.thread_id || frame.event.error_code) && <TechnicalDetails title="步骤诊断"><TechnicalValue name="关联流程编号" value={frame.event.thread_id} /><TechnicalValue name="错误代码" value={frame.event.error_code} /></TechnicalDetails>}
        {frame.event.review_choice && <p>复核决定：{label("review", frame.event.review_choice)}</p>}
        {frame.event.status_code && <p>HTTP {frame.event.status_code} · 请求耗时 {frame.event.duration_ms?.toFixed(2)} ms</p>}
      </li>)}</ol>
    </>}
    <p className="muted">只查询迁移后成功保存的请求。人工复核是独立请求，使用流程编号关联，不与原请求混用耗时；未保存或旧请求不会伪造历史。</p>
    <h2>当前会话文档检索</h2>
    <p className="muted">此页只显示当前会话中最近一次文档检索接口返回的检索、重排信息；刷新后不保留。</p>
    {!run ? <>
      <p>暂无可查看的本次检索轨迹。</p>
      <p><Link to="/evidence">前往文档证据页发起检索</Link></p>
    </> : <>
      <TechnicalDetails><TechnicalValue name="检索请求编号" value={run.requestId} /><TechnicalValue name="知识库编号" value={run.request.knowledge_base_id} /></TechnicalDetails>
      <p>检索问题：{run.request.query}</p>
      <div className="trace-flow">
        <article><h2>1 · 检索</h2>
          <p>检索模型：{run.response.retrieval.model_name}</p>
          <p>查询 token 数：{run.response.retrieval.query_token_count ?? "未提供"}</p>
          <p>接受片段数：{run.response.retrieval.accepted_chunk_ids.length}</p>
          <TechnicalDetails title="检索诊断"><TechnicalValue name="接受片段编号" value={ids(run.response.retrieval.accepted_chunk_ids)} /></TechnicalDetails>
          <p>剔除命中数：{run.response.retrieval.rejected_hit_count}</p>
        </article>
        <article><h2>2 · 重排</h2>
          <p>输入片段数：{run.response.reranking.input_count}</p>
          <p>候选片段数：{run.response.reranking.candidate_count}</p>
          <p>选中片段数：{run.response.reranking.selected_chunk_ids.length} · 重复片段数：{run.response.reranking.duplicate_chunk_ids.length} · 冗余片段数：{run.response.reranking.redundant_chunk_ids.length}</p>
          <TechnicalDetails title="重排诊断">
            <TechnicalValue name="已评分片段编号" value={ids(run.response.reranking.scored_chunk_ids)} />
            <TechnicalValue name="选中片段编号" value={ids(run.response.reranking.selected_chunk_ids)} />
            <TechnicalValue name="重复片段编号" value={ids(run.response.reranking.duplicate_chunk_ids)} />
            <TechnicalValue name="冗余片段编号" value={ids(run.response.reranking.redundant_chunk_ids)} />
          </TechnicalDetails>
        </article>
        <article><h2>3 · 引用候选</h2>
          <p>候选片段数：{run.response.bundle.candidate_count}</p>
          <p>返回引用数：{run.response.bundle.citations.length}</p>
          <p><Link to="/evidence">查看标题、页码与核验状态</Link></p>
        </article>
      </div>
    </>}
  </section>;
}
