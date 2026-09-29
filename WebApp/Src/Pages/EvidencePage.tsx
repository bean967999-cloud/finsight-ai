import { TechnicalDetails, TechnicalValue, workspaceLabel, ErrorNotice } from "../Presentation/TechnicalDetails";
import { label, explanation } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { ApiError } from "../Api/Client";
import { citationLabel, type EvidenceSearchRequest, type EvidenceSearchResponse } from "../Api/Evidence";
import { useEvidenceRun } from "../Auth/EvidenceRun";
import { useSession } from "../Auth/Session";
import { TrustNotice } from "../Presentation/TrustNotice";

export function EvidencePage() {
  const { principal, request } = useSession();
  const { run, setRun } = useEvidenceRun();
  const [workspaceId, setWorkspaceId] = usePageState("EvidencePage.workspaceId", principal?.memberships[0]?.workspace_id ?? "");
  const [knowledgeBaseId, setKnowledgeBaseId] = usePageState("EvidencePage.knowledgeBaseId", "");
  const [query, setQuery] = usePageState("EvidencePage.query", "");
  const [companyCode, setCompanyCode] = usePageState("EvidencePage.companyCode", "");
  const [documentType, setDocumentType] = usePageState<EvidenceSearchRequest["document_type"] | "">("EvidencePage.documentType", "");
  const [reportYear, setReportYear] = usePageState("EvidencePage.reportYear", "");
  const [error, setError] = usePageState("EvidencePage.error", "");
  const [busy, setBusy] = useState(false);
  const memberships = principal?.memberships ?? [];
  const membership = memberships.find((item) => item.workspace_id === workspaceId);
  const knowledgeBases = membership?.knowledge_base_ids ?? [];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError("");
    setRun(null);
    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2 || trimmedQuery.length > 2000) {
      setError("检索问题需为 2 至 2000 个字符。");
      return;
    }
    if (!knowledgeBaseId) {
      setError("请选择或填写知识库编号。");
      return;
    }
    const year = reportYear ? Number(reportYear) : undefined;
    if (year !== undefined && (!Number.isInteger(year) || year < 1900 || year > 2100)) {
      setError("报告年份需在 1900 至 2100 之间。");
      return;
    }
    const payload: EvidenceSearchRequest = {
      query: trimmedQuery,
      knowledge_base_id: knowledgeBaseId,
      ...(companyCode.trim() ? { company_code: companyCode.trim() } : {}),
      ...(documentType ? { document_type: documentType } : {}),
      ...(year ? { report_year: year } : {}),
    };
    let requestId: string | null = null;
    setBusy(true);
    try {
      const response = await request<EvidenceSearchResponse>(
        "/api/v1/evidence/search", "POST", payload, undefined,
        (id) => { requestId = id; },
      );
      setRun({ requestId, request: payload, response });
    } catch (failure) {
      const id = failure instanceof ApiError && failure.requestId ? ` 请求编号：${failure.requestId}` : "";
      setError((failure instanceof Error ? failure.message : "检索失败。").concat(id));
    } finally {
      setBusy(false);
    }
  }

  return <div className="research-layout">
    <section className="page-card">
      <h1>证据检索</h1>
      <p className="muted">从有权限的知识库检索真实文档；返回的引用可能仍是待核验状态。</p>
      <form className="research-form" onSubmit={submit}>
        <label>工作空间<select value={workspaceId} onChange={(event) => {
          setWorkspaceId(event.target.value); setKnowledgeBaseId(""); setRun(null);
        }} required>
          {memberships.length === 0 && <option value="">没有可用工作空间</option>}
          {memberships.map((item) => <option key={item.workspace_id} value={item.workspace_id}>
            {workspaceLabel(item.workspace_id)} · {label("role", item.role)}
          </option>)}
        </select></label>
        <label>知识库编号<input value={knowledgeBaseId} onChange={(event) => setKnowledgeBaseId(event.target.value.trim())}
          list="evidence-knowledge-bases" placeholder="有权访问的知识库 UUID" required />
          <datalist id="evidence-knowledge-bases">
            {knowledgeBases.map((id) => <option key={id} value={id} />)}
          </datalist>
        </label>
        <label>检索问题<textarea value={query} onChange={(event) => setQuery(event.target.value)}
          minLength={2} maxLength={2000} rows={4} required /></label>
        <label>公司代码（可选）<input value={companyCode} maxLength={32}
          onChange={(event) => setCompanyCode(event.target.value)} /></label>
        <label>文档类型（可选）<select value={documentType}
          onChange={(event) => setDocumentType(event.target.value as typeof documentType)}>
          <option value="">不限</option>
          <option value="annual_report">年报</option>
          <option value="semiannual_report">半年报</option>
          <option value="quarterly_report">季报</option>
          <option value="announcement">公告</option>
          <option value="regulatory_policy">监管政策</option>
        </select></label>
        <label>报告年份（可选）<input type="number" min="1900" max="2100"
          value={reportYear} onChange={(event) => setReportYear(event.target.value)} /></label>
        <button type="submit" disabled={busy || !workspaceId}>{busy ? "正在检索…" : "检索证据"}</button>
        {error && <ErrorNotice message={error} />}
      </form>
    </section>
    <section className="page-card" aria-live="polite">
      <h2>检索结果</h2>
      <TrustNotice summary="检索命中不等于结论已核验；请同时检查引用状态、来源及页码。" title="证据使用范围">
        <p>待核验或核验未通过的引用不能视为可靠结论依据。原文锚定核验不替代经营原因分析、全面语义审核或财务审计。</p>
        <p>引用保留公告原句；上传摘录页码不一定等于完整公告页码。</p>
      </TrustNotice>
      {!run && <p className="muted">尚无本次检索结果。</p>}
      {run && <>
        <p>候选片段数：{run.response.bundle.candidate_count}；返回引用数：{run.response.bundle.citations.length}</p>
        <TechnicalDetails><TechnicalValue name="检索请求编号" value={run.requestId} /><TechnicalValue name="知识库编号" value={run.request.knowledge_base_id} /></TechnicalDetails>
        <p><Link to="/trace">查看本次检索轨迹</Link></p>
        {run.response.bundle.citations.length === 0 && <p>未找到符合条件的引用，不能据此形成文档结论。</p>}
        {run.response.bundle.citations.map((citation) => {
          const source = citation.evidence.candidate;
          return <article className="evidence-item" key={citation.citation_id}>
            <h3>{citation.citation_id} · {source.document_title}</h3>
            <p className="result-status">{citationLabel(citation.status)}</p>
            <p className="muted">版本 {source.chunk_version} · 第 {source.page_start}{source.page_end !== source.page_start ? `–${source.page_end}` : ""} 页</p>
            <TechnicalDetails><TechnicalValue name="文档编号" value={source.document_id} /><TechnicalValue name="片段编号" value={source.chunk_id} /></TechnicalDetails>
            {source.section_path.length > 0 && <p className="muted">章节：{source.section_path.join(" / ")}</p>}
            <blockquote>{citation.quoted_text}</blockquote>
            {citation.verification_reason && <p>核验说明：{explanation(citation.verification_reason)}</p>}
            {source.source_url && /^https?:\/\//i.test(source.source_url) && <p>
              <a href={source.source_url} target="_blank" rel="noopener noreferrer">查看来源地址</a>
            </p>}
          </article>;
        })}
      </>}
    </section>
  </div>;
}
