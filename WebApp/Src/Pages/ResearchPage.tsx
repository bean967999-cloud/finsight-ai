import { TechnicalDetails, TechnicalValue, workspaceLabel, ErrorNotice } from "../Presentation/TechnicalDetails";
import { label, explanation } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { ApiError } from "../Api/Client";
import { parsePrices, resultLabel, type ResearchRequest, type ResearchResponse } from "../Api/Research";
import { AnswerMethod, TrustNotice } from "../Presentation/TrustNotice";
import { useSession } from "../Auth/Session";

type AnnualRow = {
  company_code: string; report_date: string; period_type: string;
  item_code?: string; indicator_code?: string; value: string | number | null;
  unit: string; currency?: string; consolidation_scope?: string;
  calculation_method?: string;
};
type AnnualResponse = { rows: AnnualRow[]; row_count: number; warnings: string[] };
const annualCompanies = ["600036", "000001"];
const annualYears = [2022, 2023, 2024];

export function validateAnnualRows(statements: AnnualResponse, indicators: AnnualResponse): AnnualRow[] {
  if (statements.row_count !== 12 || indicators.row_count !== 6
    || statements.rows.length !== 12 || indicators.rows.length !== 6) {
    throw new Error("三年财务数据不完整或存在多版本，请核对来源后再展示。");
  }
  const rows = [...statements.rows, ...indicators.rows];
  const seen = new Set<string>();
  for (const row of rows) {
    const metric = row.item_code ?? row.indicator_code;
    const key = `${row.company_code}/${row.report_date}/${metric}`;
    const value = row.value === null ? NaN : Number(row.value);
    if (!annualCompanies.includes(row.company_code)
      || !annualYears.some(year => row.report_date === `${year}-12-31`)
      || row.period_type !== "annual" || !Number.isFinite(value) || seen.has(key)
      || !["revenue", "n_income_attr_p", "roe"].includes(metric ?? "")) {
      throw new Error("财务记录的公司、期间、指标或数值口径不匹配。");
    }
    if (metric === "roe" ? row.unit !== "%" || !row.calculation_method
      : row.unit !== "yuan" || row.currency !== "CNY" || row.consolidation_scope !== "consolidated") {
      throw new Error("财务记录的单位或合并口径不匹配。");
    }
    seen.add(key);
  }
  for (const company of annualCompanies) for (const year of annualYears)
    for (const metric of ["revenue", "n_income_attr_p", "roe"]) {
      if (!seen.has(`${company}/${year}-12-31/${metric}`)) throw new Error("财务指标覆盖不完整。");
    }
  return rows;
}

function ThreeYearFinancialPanel() {
  const { request } = useSession();
  const [rows, setRows] = usePageState<AnnualRow[]>("ResearchPage.rows", []);
  const [warnings, setWarnings] = usePageState<string[]>("ResearchPage.warnings", []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = usePageState("ResearchPage.error", "");
  async function load() {
    setBusy(true); setError(""); setRows([]); setWarnings([]);
    const common = { entities: { company_codes: annualCompanies }, time: { report_years: annualYears }, period_type: "annual", comparison: "trend", limit: 100 };
    try {
      const [statements, indicators] = await Promise.all([
        request<AnnualResponse>("/api/v1/query/structured", "POST", { ...common, query: "比较招商银行和平安银行2022至2024年营业收入及归母净利润", intent: "financial_statement", metrics: [{ term: "营业收入" }, { term: "归母净利润" }] }),
        request<AnnualResponse>("/api/v1/query/structured", "POST", { ...common, query: "比较招商银行和平安银行2022至2024年ROE", intent: "financial_indicator", metrics: [{ term: "ROE" }] }),
      ]);
      setRows(validateAnnualRows(statements, indicators));
      setWarnings([...new Set([...statements.warnings, ...indicators.warnings])]);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "财务数据读取失败。");
    } finally { setBusy(false); }
  }
  const value = (company: string, year: number, metric: string) => Number(rows.find(row =>
    row.company_code === company && row.report_date === `${year}-12-31`
    && (row.item_code ?? row.indicator_code) === metric)?.value);
  const growth = (company: string, metric: string) => {
    const previous = value(company, 2023, metric);
    return previous === 0 ? "不可计算：基期为零" : `${((value(company, 2024, metric) / previous - 1) * 100).toFixed(2)}%`;
  };
  return <section className="page-card annual-finance" aria-live="polite">
    <h2>三年财务对比</h2>
    <TrustNotice summary="固定报告期为2022—2024年，金额单位为亿元；财务变化不直接构成投资结论。" title="财务指标与比较口径">
      <p>ROE是净资产收益率，反映利润相对股东权益的水平。本表采用年报披露的加权ROE，不能简单用归母净利润除以期末净资产。</p>
      <p>同比是与上一年度比较；百分比与百分点不同。例如ROE从16%降至14%，下降2个百分点。</p>
    </TrustNotice>
    <p className="muted">固定历史区间：2022—2024；使用2024年报披露的合并口径。数据从数据库查询，不使用页面预置财务数值；不是最新三年，也不是投资建议。</p>
    <button type="button" onClick={load} disabled={busy}>{busy ? "正在读取三年财务数据…" : "读取三年财务数据"}</button>
    {error && <ErrorNotice message={error} />}
    {rows.length > 0 && <>
      <p>已核对 18 条财务记录：12 条报表项目、6 条披露 ROE。</p>
      <div className="annual-table-wrap"><table className="annual-table">
        <caption>营业收入、归母净利润单位：亿元；ROE：百分比</caption>
        <thead><tr><th>银行</th><th>年度</th><th>营业收入</th><th>归母净利润</th><th>加权 ROE</th></tr></thead>
        <tbody>{annualCompanies.flatMap(company => annualYears.map(year => <tr key={`${company}-${year}`}>
          <th>{company === "600036" ? "招商银行" : "平安银行"}</th><td>{year}</td>
          <td>{(value(company, year, "revenue") / 100000000).toFixed(2)}</td>
          <td>{(value(company, year, "n_income_attr_p") / 100000000).toFixed(2)}</td>
          <td>{value(company, year, "roe").toFixed(2)}%</td>
        </tr>))}</tbody>
      </table></div>
      {annualCompanies.map(company => <p key={company}>
        {company === "600036" ? "招商银行" : "平安银行"}：2024年相对2023年营收变化 {growth(company, "revenue")}，归母净利润变化 {growth(company, "n_income_attr_p")}，ROE变化 {(value(company, 2024, "roe") - value(company, 2023, "roe")).toFixed(2)} 个百分点。
      </p>)}
      <p className="muted">同比计算使用数据库原值，最后才四舍五入。加权ROE沿用年报披露，不能直接用归母净利润除以期末净资产。数值变化不能单独证明经营原因或投资价值。</p>
      {warnings.map((warning, index) => <p className="muted" key={index}>{explanation(warning)}</p>)}
    </>}
    <p>来源：<a href="https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0325/2025032501341_c.pdf" target="_blank" rel="noopener noreferrer">招商银行2024年报摘要（PDF第4页）</a>；<a href="https://static.cninfo.com.cn/finalpage/2025-03-15/1222806505.PDF" target="_blank" rel="noopener noreferrer">平安银行2024年报（PDF第16—17页）</a>。财务记录按平台公共数据处理；来源页码为文件页码。</p>
  </section>;
}

export function ResearchPage() {
  const { principal, request } = useSession();
  const memberships = principal?.memberships ?? [];
  const [workspaceId, setWorkspaceId] = usePageState("ResearchPage.workspaceId", memberships[0]?.workspace_id ?? "");
  const [knowledgeBaseId, setKnowledgeBaseId] = usePageState("ResearchPage.knowledgeBaseId", "");
  const [query, setQuery] = usePageState("ResearchPage.query", "");
  const [priceInput, setPriceInput] = usePageState("ResearchPage.priceInput", "");
  const [releaseRequested, setReleaseRequested] = usePageState("ResearchPage.releaseRequested", false);
  const [result, setResult] = usePageState<ResearchResponse | null>("ResearchPage.result", null);
  const [error, setError] = usePageState("ResearchPage.error", "");
  const [busy, setBusy] = useState(false);
  const [requestId, setRequestId] = usePageState<string | null>("ResearchPage.requestId", null);

  useEffect(() => {
    if (!result?.thread_id || !result.review_pending) return;
    const controller = new AbortController();
    const refresh = () => {
      request<{ phase: string; answer: string; answer_status: ResearchResponse["answer_status"]; limitations: string[]; citations: NonNullable<ResearchResponse["citations"]>; generation?: ResearchResponse["generation"] }>(
        `/api/v1/agent/threads/${encodeURIComponent(result.thread_id!)}/content`, "GET", undefined, controller.signal,
      ).then(flow => {
        if (!controller.signal.aborted) setResult(previous => previous?.thread_id === result.thread_id
          ? { ...previous, answer: flow.answer, answer_status: flow.answer_status, limitations: flow.limitations,
              citations: flow.citations, generation: flow.generation, review_pending: flow.phase === "awaiting_review" } : previous);
      }).catch(() => { /* Keep the saved response if status cannot be refreshed. */ });
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => { controller.abort(); window.removeEventListener("focus", refresh); };
  }, [result?.thread_id, request]);

  const membership = memberships.find((item) => item.workspace_id === workspaceId);
  const canSubmit = membership?.role === "researcher" || membership?.role === "workspace_admin";
  const knowledgeBases = membership?.knowledge_base_ids ?? [];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setResult(null);
    setRequestId(null);
    setError("");
    if (!canSubmit) {
      setError("当前工作空间没有提交研究问题的权限。");
      return;
    }
    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2 || trimmedQuery.length > 2000) {
      setError("研究问题需为 2 至 2000 个字符。");
      return;
    }
    let payload: ResearchRequest;
    try {
      const prices = parsePrices(priceInput);
      payload = {
        query: trimmedQuery,
        workspace_id: workspaceId,
        ...(knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : {}),
        ...(prices ? { prices } : {}),
        release_requested: releaseRequested,
      };
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "输入内容无效。");
      return;
    }
    setBusy(true);
    try {
      setResult(await request<ResearchResponse>("/api/v1/agent/query", "POST", payload, undefined, setRequestId));
    } catch (failure) {
      const requestId = failure instanceof ApiError && failure.requestId
        ? ` 请求编号：${failure.requestId}` : "";
      setError((failure instanceof Error ? failure.message : "请求失败，请稍后重试。") + requestId);
    } finally {
      setBusy(false);
    }
  }

  return <div className="research-layout">
    <ThreeYearFinancialPanel />
    <section className="page-card">
      <h1>投研首页</h1>
      <p className="muted">基于授权资料开展研究，结果附来源与核验信息。</p>
      <form className="research-form" onSubmit={submit}>
        <label>工作空间
          <select value={workspaceId} onChange={(event) => {
            setWorkspaceId(event.target.value);
            setKnowledgeBaseId("");
            setResult(null);
          }} required>
            {memberships.length === 0 && <option value="">没有可用工作空间</option>}
            {memberships.map((item) => <option key={item.workspace_id} value={item.workspace_id}>
              {workspaceLabel(item.workspace_id)} · {label("role", item.role)}
            </option>)}
          </select>
        </label>
        <label>研究问题
          <textarea value={query} onChange={(event) => setQuery(event.target.value)}
            minLength={2} maxLength={2000} rows={5} required
            placeholder="例如：分析某资产的风险；文档类问题需要选择有权限的知识库。" />
        </label>
        <label>知识库编号（文档类问题必填）
          <input value={knowledgeBaseId} onChange={(event) => setKnowledgeBaseId(event.target.value.trim())}
            list="granted-knowledge-bases" placeholder="填写有权访问的知识库 UUID" />
          <datalist id="granted-knowledge-bases">
            {knowledgeBases.map((id) => <option key={id} value={id} />)}
          </datalist>
        </label>
        <label>价格序列（风险分析时填写；逗号或空格分隔，至少 3 个正数）
          <textarea value={priceInput} onChange={(event) => setPriceInput(event.target.value)}
            rows={2} placeholder="可留空；不使用虚构的默认价格" />
        </label>
        <label className="checkbox-label"><input type="checkbox" checked={releaseRequested}
          onChange={(event) => setReleaseRequested(event.target.checked)} /> 请求对外发布（需要人工确认流程）</label>
        <button type="submit" disabled={busy || !canSubmit || !workspaceId}>
          {busy ? "正在执行研究…" : "提交研究问题"}
        </button>
        {!canSubmit && <p className="muted">该工作空间角色仅可查看，不能提交研究问题。</p>}
        {error && <ErrorNotice message={error} />}
      </form>
    </section>

    <section className="page-card" aria-live="polite">
      <h2>本次结果</h2>
      {busy && <p>请求已提交，正在等待服务端返回。此处不是后台任务进度。</p>}
      {!busy && !result && <p className="muted">尚无本次结果。提交后将显示真实返回状态。</p>}
      {result && <>
        <p className="result-status">{resultLabel(result)}</p>
        {requestId && <p><Link to={`/trace?requestId=${encodeURIComponent(requestId)}`}>查询本次研究完整轨迹</Link></p>}
        <p className="muted">研究类型：{label("intent", result.intent)}</p>
        <TechnicalDetails><TechnicalValue name="研究请求编号" value={requestId} /><TechnicalValue name="审核流程编号" value={result.thread_id} /><TechnicalValue name="工作空间编号" value={workspaceId} /><TechnicalValue name="知识库编号" value={knowledgeBaseId} /></TechnicalDetails>
        {result.review_pending && result.thread_id && <p><Link to={`/review?threadId=${encodeURIComponent(result.thread_id)}`}>查看人工审核流程（需要相应权限）</Link></p>}
        <div className="answer-text">{result.answer}</div>
        <AnswerMethod generation={result.generation} />
        <TrustNotice summary="答案仅在所列证据与核验范围内成立，不构成投资建议。" title="如何理解引用与回答">
          <p>原文锚定核验检查引用与来源、数值和单位的一致性，不等于全面语义审核或财务审计。</p>
          <p>上传摘录的页码与完整原公告页码可能不同，请结合来源文件说明。每股股息是现金分配，股息率还需要股价作为分母。</p>
        </TrustNotice>
        {(result.citations ?? []).map((citation) => <article key={citation.citation_id}>
          <h3>{citation.citation_id} · {label("citation", citation.status)}</h3>
          <p>{citation.evidence.candidate.document_title} · 上传文件第 {citation.evidence.candidate.page_start} 页</p>
          <blockquote>{citation.quoted_text}</blockquote>
          <p>{explanation(citation.verification_reason)}</p>
          {citation.evidence.candidate.source_url?.startsWith("https://") && <a href={citation.evidence.candidate.source_url} target="_blank" rel="noopener noreferrer">完整公告来源（原文页码以文件说明为准）</a>}
        </article>)}
        {result.limitations.length > 0 && <>
          <h3>限制条件</h3>
          <ul>{result.limitations.map((item, index) => <li key={`${index}-${item}`}>{explanation(item)}</li>)}</ul>
        </>}
        {result.evidence.length > 0 && <>
          <h3>接口返回的证据摘要</h3>
          <ul>{result.evidence.map((item, index) => <li key={`${index}-${item}`}>{explanation(item)}</li>)}</ul>
          <p className="muted">证据摘要不替代原文引用，请结合来源、页码与核验状态查看。</p>
        </>}
      </>}
    </section>
  </div>;
}
