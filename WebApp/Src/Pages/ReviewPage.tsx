import { TechnicalDetails, TechnicalValue, ErrorNotice } from "../Presentation/TechnicalDetails";
import { label, explanation } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { useSession } from "../Auth/Session";
import type { Citation } from "../Api/Evidence";
import type { GenerationInfo } from "../Api/Research";
import { requestFailure } from "../Api/Client";
import { AnswerMethod, TrustNotice } from "../Presentation/TrustNotice";

interface ReviewFlow {
  thread_id: string; phase: string; answer_status: string; answer: string;
  citations: Citation[]; limitations: string[];
  review_request: Record<string, unknown> | null;
  review_outcome: { choice: string; note: string } | null;
  generation?: GenerationInfo | null;
}

export function ReviewPage() {
  const { principal, request } = useSession();
  const [params] = useSearchParams();
  const [threadId, setThreadId] = usePageState(`ReviewPage.threadId:${params.get("threadId") ?? "default"}`, params.get("threadId") ?? "");
  const [flow, setFlow] = usePageState<ReviewFlow | null>(`ReviewPage.flow:${params.get("threadId") ?? "default"}`, null);
  const [note, setNote] = usePageState(`ReviewPage.note:${params.get("threadId") ?? "default"}`, "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = usePageState(`ReviewPage.error:${params.get("threadId") ?? "default"}`, "");
  const canReview = principal?.memberships.some(m => m.role === "reviewer") ?? false;
  async function load(event: FormEvent) {
    event.preventDefault(); setError(""); setFlow(null); setBusy(true);
    try { setFlow(await request<ReviewFlow>(`/api/v1/agent/threads/${encodeURIComponent(threadId.trim())}/content`, "GET")); }
    catch (failure) { setError(requestFailure(failure, "流程读取失败。")); }
    finally { setBusy(false); }
  }
  async function decide(choice: "confirmed" | "rejected") {
    if (!flow || busy) return;
    setError("");
    if (choice === "rejected" && !note.trim()) { setError("驳回必须说明原因。"); return; }
    setBusy(true);
    try {
      await request(`/api/v1/agent/threads/${encodeURIComponent(flow.thread_id)}/review`, "POST", { choice, note: note.trim() });
      setFlow(await request<ReviewFlow>(`/api/v1/agent/threads/${encodeURIComponent(flow.thread_id)}/content`, "GET"));
    }
    catch (failure) { setError(requestFailure(failure, "审核失败，请重新读取流程。")); }
    finally { setBusy(false); }
  }
  return <section className="page-card">
    <h1>人工审核</h1>
    <p>按流程编号读取服务端保存的结果。人工确认不等于来源核验，不执行交易或自动对外发布。</p>
    <TrustNotice summary="审核决定与来源核验是两个独立状态；确认或驳回均不代表投资建议。" />
    <form className="research-form" onSubmit={load}>
      <label>待审核流程编号<input required value={threadId} onChange={e => { setThreadId(e.target.value); setFlow(null); }} /></label>
      <button disabled={busy}>读取审核流程</button>
    </form>
    {error && <ErrorNotice message={error} />}
    {flow && <>
      <h2>保存的研究结果</h2>
      <TechnicalDetails><TechnicalValue name="审核流程编号" value={flow.thread_id} /></TechnicalDetails>
      <p>流程状态：{label("phase", flow.phase)} · 答案状态：{label("answer", flow.answer_status)}</p>
      <div className="answer-text">{flow.answer}</div>
      <AnswerMethod generation={flow.generation} />
      <ul>{flow.limitations.map(item => <li key={item}>{explanation(item)}</li>)}</ul>
      {flow.citations.map(c => <article key={c.citation_id}><h3>{c.citation_id} · {label("citation", c.status)}</h3>
        <p>{c.evidence.candidate.document_title} · 上传文件第 {c.evidence.candidate.page_start} 页</p>
        <blockquote>{c.quoted_text}</blockquote><p>{explanation(c.verification_reason)}</p>
        {c.evidence.candidate.source_url?.startsWith("https://") && <a href={c.evidence.candidate.source_url} target="_blank" rel="noopener noreferrer">完整公告来源（原文页码以文件说明为准）</a>}
      </article>)}
      {flow.review_outcome ? <p>审核结果：{label("review", flow.review_outcome.choice)} · {flow.review_outcome.note}</p> : <>
        <label>审核说明<textarea maxLength={1000} value={note} onChange={e => setNote(e.target.value)} /></label>
        <button disabled={busy || !canReview || flow.phase !== "awaiting_review"} onClick={() => void decide("confirmed")}>确认本次审核</button>
        <button disabled={busy || !canReview || flow.phase !== "awaiting_review"} onClick={() => void decide("rejected")}>驳回本次审核</button>
        {!canReview && <p>当前角色不能作出审核决定；后端仍按本流程所在空间重新验证权限。</p>}
      </>}
    </>}
  </section>;
}
