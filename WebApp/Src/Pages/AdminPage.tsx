import { TechnicalDetails, TechnicalValue, workspaceLabel, ErrorNotice } from "../Presentation/TechnicalDetails";
import { label } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useRef, useState } from "react";
import { ApiError } from "../Api/Client";
import { auditOutcome, type AuditPage } from "../Api/Audit";
import { useSession } from "../Auth/Session";

export function AdminPage() {
  const { principal, request } = useSession();
  const memberships = principal?.memberships ?? [];
  const managed = memberships.filter((item) => item.role === "workspace_admin");
  const [workspaceId, setWorkspaceId] = usePageState("AdminPage.workspaceId", managed[0]?.workspace_id ?? "");
  const [page, setPage] = usePageState<AuditPage | null>("AdminPage.page", null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = usePageState("AdminPage.error", "");

  async function load(offset = 0) {
    if (busy || !workspaceId) return;
    setBusy(true);
    setError("");
    setPage(null);
    try {
      const received = await request<AuditPage>(
        `/api/v1/admin/workspaces/${workspaceId}/audit?offset=${offset}&limit=20`, "GET",
      );
      setPage(received);
    } catch (failure) {
      const id = failure instanceof ApiError && failure.requestId ? ` 请求编号：${failure.requestId}` : "";
      setError((failure instanceof Error ? failure.message : "审计查询失败。") + id);
    } finally {
      setBusy(false);
    }
  }

  return <div className="evaluation-layout">
    <section className="page-card evaluation-section">
      <h1>当前身份与工作空间</h1>
      <p className="muted">查看当前成员关系与审计记录；此页面不修改账号、角色或授权。</p>
      <TechnicalDetails><TechnicalValue name="用户编号" value={principal?.user_id} />{memberships.map(item => <TechnicalValue key={item.workspace_id} name="工作空间编号" value={item.workspace_id} />)}</TechnicalDetails>
      <ul>{memberships.map((item) => <li key={item.workspace_id}>
        {workspaceLabel(item.workspace_id)} · {label("role", item.role)} · 显式知识库授权 {item.knowledge_base_ids.length} 个
      </li>)}</ul>
      <p className="muted">以上成员关系来自登录时的身份接口；查询权限仍由后端按当前成员关系重新确认。显式授权数量不等于工作空间知识库总数。</p>
    </section>
    <section className="page-card evaluation-section">
      <h2>工作空间审计记录</h2>
      <div className="audit-controls">
        <label>管理范围<select value={workspaceId} disabled={busy} onChange={(event) => {
          setWorkspaceId(event.target.value); setPage(null); setError("");
        }}>
          {managed.map((item) => <option key={item.workspace_id} value={item.workspace_id}>{workspaceLabel(item.workspace_id)}</option>)}
        </select></label>
        <button type="button" onClick={() => void load()} disabled={busy || !workspaceId}>
          {busy ? "正在查询…" : "查询最新记录"}
        </button>
      </div>
      <p className="muted">只显示明确归属于所选空间的操作元数据，不显示提问正文、令牌或文档内容。无空间归属的登录、拒绝访问及历史记录不包含在此列表中。</p>
      {error && <ErrorNotice message={error} />}
      {!page && !busy && !error && <p>选择工作空间后查询；尚未读取记录。</p>}
      {page && <>
        {page.records.length === 0 ? <p>当前查询范围内没有记录，不等于系统没有发生过操作。</p> : <div className="audit-table-wrap">
          <table className="audit-table"><thead><tr>
            <th>开始时间</th><th>操作与路由</th><th>结果</th><th>操作人</th><th>请求编号</th>
          </tr></thead><tbody>{page.records.map((item) => <tr key={item.request_id}>
            <td>{item.started_at.replace("T", " ")}<small>完成：{item.finished_at?.replace("T", " ") ?? "未记录"}</small></td>
            <td>{label("action", item.action)}<TechnicalDetails title="操作详情"><TechnicalValue name="原始操作码" value={item.action} /><TechnicalValue name="接口路由" value={`${item.method} ${item.route_pattern}`} /></TechnicalDetails></td>
            <td>{auditOutcome(item.outcome)}<small>HTTP {item.status_code ?? "未记录"}</small></td>
            <td><TechnicalDetails title="操作人详情"><TechnicalValue name="操作人编号" value={item.actor_user_id} /></TechnicalDetails></td><td><TechnicalDetails title="请求详情"><TechnicalValue name="请求编号" value={item.request_id} /></TechnicalDetails></td>
          </tr>)}</tbody></table>
        </div>}
        <div className="audit-controls">
          <button type="button" disabled={busy || page.offset === 0}
            onClick={() => void load(Math.max(0, page.offset - page.limit))}>上一页</button>
          <span>偏移 {page.offset} · 每页最多 {page.limit} 条</span>
          <button type="button" disabled={busy || !page.has_more || page.offset + page.limit > 10000}
            onClick={() => void load(page.offset + page.limit)}>下一页</button>
        </div>
        <p className="muted">按时间倒序查询；持续新增记录时翻页可能出现重复，当前不是固定快照或完整导出。</p>
      </>}
    </section>
  </div>;
}

interface ManagedDocument {
  document_id: number; title: string; report_year: number | null;
  parse_job_id: number | null; parse_status: string | null;
}
interface BackgroundJob {
  job_id: number; status: string; attempt_count: number;
  result_ref: string | null; error_code: string | null;
}

export function DocumentTasksPage() {
  const { principal, request } = useSession();
  const bases = [...new Set(principal?.memberships.filter(m => m.role === "workspace_admin")
    .flatMap(m => m.knowledge_base_ids) ?? [])];
  const [kb, setKb] = usePageState("DocumentTasksPage.kb", bases[0] ?? "");
  const [title, setTitle] = usePageState("DocumentTasksPage.title", "");
  const [company, setCompany] = usePageState("DocumentTasksPage.company", "");
  const [year, setYear] = usePageState("DocumentTasksPage.year", "2024");
  const [source, setSource] = usePageState("DocumentTasksPage.source", "");
  const [file, setFile] = useState<File | null>(null);
  const [documents, setDocuments] = usePageState<ManagedDocument[]>("DocumentTasksPage.documents", []);
  const [documentId, setDocumentId] = usePageState("DocumentTasksPage.documentId", "");
  const [parseId, setParseId] = usePageState("DocumentTasksPage.parseId", "");
  const [jobId, setJobId] = usePageState("DocumentTasksPage.jobId", "");
  const [job, setJob] = usePageState<BackgroundJob | null>("DocumentTasksPage.job", null);
  const [message, setMessage] = usePageState("DocumentTasksPage.message", "");
  const [error, setError] = usePageState("DocumentTasksPage.error", "");
  const [busy, setBusy] = useState(false);
  const uploadKey = useRef(crypto.randomUUID());
  const taskKey = useRef(crypto.randomUUID());

  async function action(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await work(); }
    catch (failure) {
      setError((failure instanceof Error ? failure.message : "操作失败") +
        (failure instanceof ApiError && failure.requestId ? ` 请求编号：${failure.requestId}` : ""));
    } finally { setBusy(false); }
  }
  async function load() {
    const result = await request<{ documents: ManagedDocument[] }>(
      `/api/v1/jobs/documents?knowledge_base_id=${encodeURIComponent(kb)}`, "GET");
    setDocuments(result.documents);
  }
  async function upload() {
    if (!file || file.size > 4 * 1024 * 1024) throw new Error("请选择4MB以内的PDF。");
    const encoded = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = () => reject(new Error("文件读取失败"));
      reader.readAsDataURL(file);
    });
    const result = await request<{ document_id: number }>("/api/v1/jobs/documents/upload", "POST", {
      knowledge_base_id: kb, idempotency_key: uploadKey.current, title,
      company_code: company || null, report_year: Number(year), source_url: source || null,
      pdf_base64: encoded,
    });
    setDocumentId(String(result.document_id));
    uploadKey.current = crypto.randomUUID();
    setMessage(`文档 ${result.document_id} 已登记；尚未解析或索引。`);
    await load();
  }
  async function submit(kind: "document_parse" | "chunk_index") {
    const task = kind === "document_parse" ? { kind, document_id: Number(documentId) }
      : { kind, parse_job_id: Number(parseId), chunk_version: 1 };
    const result = await request<{ job: BackgroundJob }>("/api/v1/jobs", "POST", {
      knowledge_base_id: kb, idempotency_key: taskKey.current, task, max_attempts: 2,
    });
    setJobId(String(result.job.job_id)); setJob(result.job);
    taskKey.current = crypto.randomUUID();
    setMessage("任务已提交。提交成功不等于后台执行成功，请刷新状态。");
  }
  async function refresh() {
    const result = await request<BackgroundJob>(`/api/v1/jobs/${Number(jobId)}`, "GET");
    setJob(result);
    if (result.status === "succeeded" && result.result_ref?.startsWith("document_parse_job:"))
      setParseId(result.result_ref.split(":")[1]);
  }
  return <div className="evaluation-layout documents-workflow">
    <section className="page-card evaluation-section">
      <h1>文档与后台任务</h1>
      <p className="muted">公告登记 → 提交解析 → 确认成功 → 生成切块 → 提交索引。每一步单独验收，不自动把排队当成完成。</p>
      <label>知识库编号<input aria-label="知识库编号" value={kb} disabled={busy} onChange={e => {
        setKb(e.target.value); setDocuments([]); setJob(null); setDocumentId(""); setParseId(""); setJobId("");
      }} /></label>
      <p className="muted">后端重新核验管理权限；填写编号本身不会获得授权。</p>
      <button disabled={busy || !kb} onClick={() => void action(load)}>读取文档列表</button>
      <ul>{documents.map(d => <li key={d.document_id}>
        <button disabled={busy} onClick={() => { setDocumentId(String(d.document_id));
          setParseId(d.parse_status === "succeeded" ? String(d.parse_job_id) : ""); }}>
          文档 {d.document_id} · {d.title} · 解析 {d.parse_status ? label("job", d.parse_status) : "未执行"}
        </button>
      </li>)}</ul>
    </section>
    <section className="page-card evaluation-section">
      <h2>上传公告</h2>
      <label>公告标题<input value={title} onChange={e => setTitle(e.target.value)} disabled={busy} /></label>
      <label>公司代码<input value={company} onChange={e => setCompany(e.target.value)} disabled={busy} /></label>
      <label>报告年份<input type="number" min="1900" max="2100" value={year} onChange={e => setYear(e.target.value)} disabled={busy} /></label>
      <label>来源链接<input value={source} onChange={e => setSource(e.target.value)} disabled={busy} /></label>
      <label>公告PDF<input type="file" accept="application/pdf,.pdf" disabled={busy} onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
      <p className="muted">仅支持4MB以内的公告。登记阶段只验证大小和PDF头尾标记，实际能否解析以后台结果为准。相同文件元数据冲突不会覆盖；这不是大型年报批量上传功能。</p>
      <button disabled={busy || !kb || !title || !file} onClick={() => void action(upload)}>登记公告</button>
    </section>
    <section className="page-card evaluation-section">
      <h2>解析、切块与索引</h2>
      <label>文档编号<input type="number" min="1" value={documentId} onChange={e => setDocumentId(e.target.value)} disabled={busy} /></label>
      <button disabled={busy || !documentId || !kb} onClick={() => void action(() => submit("document_parse"))}>提交解析任务</button>
      <label>成功解析编号<input type="number" min="1" value={parseId} onChange={e => setParseId(e.target.value)} disabled={busy} /></label>
      <button disabled={busy || !parseId || !kb} onClick={() => void action(async () => {
        const result = await request<{ chunk_count: number }>("/api/v1/jobs/documents/chunks", "POST", {
          knowledge_base_id: kb, parse_job_id: Number(parseId),
        }); setMessage(`已生成或复用 ${result.chunk_count} 个切块；尚未执行索引。`);
      })}>生成并校验切块</button>
      <button disabled={busy || !parseId || !kb} onClick={() => void action(() => submit("chunk_index"))}>提交索引任务</button>
      <label>后台任务编号<input type="number" min="1" value={jobId} onChange={e => setJobId(e.target.value)} disabled={busy} /></label>
      <button disabled={busy || !jobId} onClick={() => void action(refresh)}>刷新任务状态</button>
      {job && <p role="status">任务 {job.job_id}：{label("job", job.status)}；执行次数 {job.attempt_count}</p>}
      {job && <TechnicalDetails><TechnicalValue name="后台任务编号" value={job.job_id} /><TechnicalValue name="结果引用" value={job.result_ref} /><TechnicalValue name="错误代码" value={job.error_code} /></TechnicalDetails>}
      {message && <p role="status">{message}</p>}
      {error && <ErrorNotice message={error} />}
    </section>
  </div>;
}
