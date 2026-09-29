// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { App } from "./App";
import { SessionProvider } from "./Auth/Session";
import { validateAnnualRows } from "./Pages/ResearchPage";

function annualFixture() {
  const common = ["600036", "000001"].flatMap(company_code => [2022, 2023, 2024].map(year => ({
    company_code, report_date: `${year}-12-31`, period_type: "annual",
  })));
  return {
    statements: { rows: common.flatMap(row => ["revenue", "n_income_attr_p"].map(item_code => ({
      ...row, item_code, value: "100000000", unit: "yuan", currency: "CNY", consolidation_scope: "consolidated",
    }))), row_count: 12, warnings: [] },
    indicators: { rows: common.map(row => ({ ...row, indicator_code: "roe", value: "10", unit: "%", calculation_method: "fixture disclosed weighted ROE" })), row_count: 6, warnings: [] },
  };
}

it("requires all annual company/metric keys and canonical units before displaying finance", () => {
  const { statements, indicators } = annualFixture();
  expect(validateAnnualRows(statements, indicators)).toHaveLength(18);
  expect(() => validateAnnualRows({ ...statements, rows: statements.rows.slice(1) }, indicators)).toThrow();
  expect(() => validateAnnualRows({ ...statements, rows: statements.rows.map((row, i) => i === 0 ? { ...row, unit: "million_yuan" } : row) }, indicators)).toThrow();
  expect(() => validateAnnualRows({ ...statements, rows: statements.rows.map((row, i) => i === 1 ? statements.rows[0] : row) }, indicators)).toThrow();
  expect(() => validateAnnualRows(statements, { ...indicators, rows: indicators.rows.map((row, i) => i === 0 ? { ...row, value: "invalid" } : row) })).toThrow();
  expect(() => validateAnnualRows(statements, { ...indicators, rows: indicators.rows.map((row, i) => i === 0 ? { ...row, report_date: "2025-12-31" } : row) })).toThrow();
});

const workspace = "11111111-1111-4111-8111-111111111111";
const knowledge = "22222222-2222-4222-8222-222222222222";
vi.mock("./Pages/DrawdownChart", () => ({ DrawdownChart: () => null }));

afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });

function setup(role = "researcher") {
  const fetchMock = vi.fn(async (path: string, init: RequestInit) => {
    let body: unknown;
    if (path.endsWith("/auth/login")) body = { access_token: "fixture-token", token_type: "bearer", expires_in_seconds: 1800 };
    else if (path.endsWith("/auth/me")) body = {
      user_id: "33333333-3333-4333-8333-333333333333", active: true,
      memberships: [{ workspace_id: workspace, role, knowledge_base_ids: [knowledge] }],
    };
    else if (path.endsWith("/query/structured")) {
      const payload = JSON.parse(init.body as string);
      body = payload.intent === "financial_statement" ? annualFixture().statements : annualFixture().indicators;
    }
    else if (path.endsWith("/agent/query")) body = {
      thread_id: null, review_pending: false, review_request: null, intent: "risk_analysis",
      answer: "测试响应：缺少价格，不能形成风险结论。", answer_status: "insufficient_evidence",
      limitations: ["测试限制：没有价格"], evidence: [], risk_metrics: null,
    };
    else if (path.endsWith("/evidence/search")) body = {
      bundle: { query_sha256: "fixture", candidate_count: 0, citations: [] },
      retrieval: { model_name: "fixture-retriever", query_token_count: null, accepted_chunk_ids: [], rejected_hit_count: 0 },
      reranking: { input_count: 0, candidate_count: 0, scored_chunk_ids: [], selected_chunk_ids: [], duplicate_chunk_ids: [], redundant_chunk_ids: [] },
    };
    else if (path.includes("/agent/traces/")) body = {
      request_id: "44444444-4444-4444-8444-444444444444", workspace_id: workspace,
      owner_user_id: "fixture-owner", knowledge_base_id: null, truncated: false,
      frames: [{ sequence: 1, occurred_at: "2026-09-28T00:00:00Z", event: {
        kind: "tool_completed", tool: "risk_calculation", tool_status: "succeeded", duration_ms: 2,
      } }],
    };
    else if (path.endsWith("/risk/portfolio-report/from-db")) body = {
      portfolio: { tickers: ["A", "B"], weights: [0.5, 0.5], adjustment_type: "none",
        aligned_observations: 20, returns: [{ period_start: "2024-01-01", period_end: "2024-01-02", value: 0.01 }],
        annualized_mean_return: 0.1, annualized_volatility: 0.2,
        correlation_matrix: [[1, 0.3], [0.3, 1]],
        risk_contributions: [{ ticker: "A", annualized_volatility_contribution: 0.1, share_of_portfolio_volatility: 0.5 },
          { ticker: "B", annualized_volatility_contribution: 0.1, share_of_portfolio_volatility: 0.5 }],
      }, sources: [["A", "fixture", 1], ["B", "fixture", 1]], warnings: ["fixture-warning"],
    };
    else if (path.includes("/jobs/documents?")) body = { documents: [{ document_id: 1, title: "Fixture disclosure", report_year: 2024, parse_job_id: 8, parse_status: "succeeded" }] };
    else if (path.endsWith("/jobs/44")) body = { job_id: 44, status: "queued", attempt_count: 0, result_ref: null, error_code: null };
    else if (path.endsWith("/evaluation/overview")) body = {
      generated_at:"2026-09-28T00:00:00Z", execution:"local_synthetic_recomputed_on_request",
      research:{suite_name:"fixture",suite_version:"v1",source:"synthetic_fixture",tool_cases:[],numeric_cases:[],
        metrics:{tool_case_count:0,numeric_case_count:0,intent_accuracy:0,tool_set_accuracy:0,limitation_accuracy:0,numeric_metric_pass_rate:0}},
      retrieval:{dataset_name:"fixture-real",dataset_version:"v2",status:"observations_scored",unrun_question_ids:[],
        metrics:{question_count:40,answerable_count:20,refusal_count:20,retrieval_recall_at_k:1,rerank_hit_rate_at_n:1,citation_correctness:0.95,refusal_accuracy:1,mean_latency_ms:100},
        cases:Array.from({length:40},(_,i)=>({question_id:`GQ-${String(i+1).padStart(3,"0")}`,should_refuse:i>=20,refused:i>=20,passed:i!==13,
          retrieval_rank:i>=20?null:1,rerank_rank:i>=20?null:1,citation_correct:i<20&&i!==13,failure_reasons:i===13?["citation_not_supported"]:[]}))},
    };
    else if (path.includes("/audit?")) body = { workspace_id: workspace, records: [], offset: 0, limit: 20, has_more: false };
    else throw new Error(`Unexpected fixture request: ${path}`);
    if (!path.endsWith("/auth/login")) expect(new Headers(init.headers).get("Authorization")).toBe("Bearer fixture-token");
    return new Response(JSON.stringify(body), { status: 200, headers: { "X-Request-ID": "fixture-request" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/research"]}><SessionProvider><App /></SessionProvider></MemoryRouter>);
  return fetchMock;
}

async function login() {
  fireEvent.change(await screen.findByLabelText("邮箱"), { target: { value: "fixture@example.com" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "fixture-password" } });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("heading", { name: "投研首页" });
}

it("connects protected routing, login and an insufficient-evidence research result", async () => {
  const fetchMock = setup();
  await login();
  expect(screen.queryByRole("link", { name: "管理与审计" })).toBeNull();
  expect(screen.queryByRole("link", { name: "文档与任务" })).toBeNull();
  fireEvent.change(screen.getByLabelText("研究问题"), { target: { value: "分析风险情况" } });
  fireEvent.click(screen.getByRole("button", { name: "提交研究问题" }));
  await screen.findByText("证据不足 · 不形成结论");
  const call = fetchMock.mock.calls.find(([path]) => path.endsWith("/agent/query"));
  expect(JSON.parse(String(call?.[1].body))).toMatchObject({ query: "分析风险情况", workspace_id: workspace });
  expect(JSON.parse(String(call?.[1].body))).not.toHaveProperty("prices");
});

it("shows real question counts and a failed case without hiding it behind summary metrics", async () => {
  setup("workspace_admin");
  await login();
  fireEvent.click(screen.getByRole("link", {name:"评估看板"}));
  await screen.findByText(/真实题数：40/);
  expect(screen.getByText(/可回答：20/)).toBeTruthy();
  expect(screen.getByText("整题通过：39 / 40")).toBeTruthy();
  expect(screen.getByText("GQ-014 · 未通过")).toBeTruthy();
  expect(screen.getByText("失败原因：引用缺少来源支持")).toBeTruthy();
});

it("links the same evidence-search response to its trace without fabricated citations", async () => {
  setup();
  await login();
  fireEvent.click(screen.getByRole("link", { name: "文档证据" }));
  fireEvent.change(screen.getByLabelText("知识库编号"), { target: { value: knowledge } });
  fireEvent.change(screen.getByLabelText("检索问题"), { target: { value: "查询年报资产" } });
  fireEvent.click(screen.getByRole("button", { name: "检索证据" }));
  await screen.findByText("未找到符合条件的引用，不能据此形成文档结论。");
  fireEvent.click(screen.getByRole("link", { name: "查看本次检索轨迹" }));
  await screen.findByText("检索模型：fixture-retriever");
  const identifier = screen.getByText("fixture-request");
  expect(identifier.closest("details")?.hasAttribute("open")).toBe(false);
  expect(identifier.closest("details")?.querySelector("summary")?.textContent).toBe("技术详情");
});

it("lets an admin read scoped audit metadata and clears the session on logout", async () => {
  setup("workspace_admin");
  await login();
  fireEvent.click(screen.getByRole("link", { name: "管理与审计" }));
  fireEvent.click(screen.getByRole("button", { name: "查询最新记录" }));
  await screen.findByText("当前查询范围内没有记录，不等于系统没有发生过操作。");
  fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
  await screen.findByRole("heading", { name: "登录工作空间" });
});

it("reads a stored research trace through the authorized session", async () => {
  setup(); await login();
  fireEvent.click(screen.getByRole("link", { name: "执行轨迹" }));
  fireEvent.change(screen.getByLabelText("研究请求编号"), { target: { value: "44444444-4444-4444-8444-444444444444" } });
  fireEvent.click(screen.getByRole("button", { name: "查询研究轨迹" }));
  await screen.findByText("工具执行结束");
  expect(screen.getByText(/耗时 2.00 ms/)).toBeTruthy();
});

it("submits the exact portfolio weights and renders returned contributions", async () => {
  const fetchMock = setup(); await login();
  fireEvent.click(screen.getByRole("link", { name: "风险看板" }));
  await screen.findByRole("heading", { name: "组合风险" });
  for (const [label, value] of [["组合交易所", "SSE"], ["组合数据源", "fixture"], ["组合复权方式", "none"],
    ["组合开始日期", "2024-01-01"], ["组合结束日期", "2024-02-01"], ["资产 1 代码", "A"], ["资产 2 代码", "B"]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "计算组合风险" }));
  await screen.findByRole("heading", { name: "风险贡献度" });
  const call = fetchMock.mock.calls.find(([path]) => path.endsWith("/portfolio-report/from-db"));
  expect(JSON.parse(String(call?.[1].body)).positions.map((item: { weight: number }) => item.weight)).toEqual([0.5, 0.5]);
});

it("lets an admin select a scoped document and distinguishes queued from succeeded", async () => {
  setup("workspace_admin"); await login();
  fireEvent.click(screen.getByRole("link", { name: "文档与任务" }));
  expect(screen.getByRole("button", { name: "提交解析任务" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "读取文档列表" }));
  fireEvent.click(await screen.findByRole("button", { name: /文档 1 · Fixture disclosure/ }));
  expect((screen.getByLabelText("成功解析编号") as HTMLInputElement).value).toBe("8");
  fireEvent.change(screen.getByLabelText("后台任务编号"), { target: { value: "44" } });
  fireEvent.click(screen.getByRole("button", { name: "刷新任务状态" }));
  await screen.findByText(/任务 44：已排队；执行次数 0/);
  expect(screen.queryByText(/任务 44：执行成功/)).toBeNull();
});

it("loads annual finance through two structured requests without submitting research", async () => {
  const fetchMock = setup("viewer"); await login();
  expect(screen.queryByText(/已核对 18 条财务记录/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "读取三年财务数据" }));
  await screen.findByText(/已核对 18 条财务记录/);
  const calls = fetchMock.mock.calls.filter(([path]) => path.endsWith("/query/structured"));
  expect(calls).toHaveLength(2);
  for (const [, init] of calls) {
    const payload = JSON.parse(init.body as string);
    expect(payload.time.report_years).toEqual([2022, 2023, 2024]);
    expect(payload.entities.company_codes).toEqual(["600036", "000001"]);
    expect(payload.period_type).toBe("annual");
  }
  expect(fetchMock.mock.calls.some(([path]) => path.endsWith("/agent/query"))).toBe(false);
});


it("keeps the research draft and result when navigating away and returning", async () => {
  const fetchMock = setup();
  await login();
  fireEvent.change(screen.getByLabelText("研究问题"), { target: { value: "分析风险情况" } });
  fireEvent.click(screen.getByRole("button", { name: "提交研究问题" }));
  await screen.findByText("证据不足 · 不形成结论");
  fireEvent.click(screen.getByRole("link", { name: "人工审核" }));
  await screen.findByRole("heading", { name: "人工审核" });
  fireEvent.click(screen.getByRole("link", { name: "投研首页" }));
  await screen.findByText("证据不足 · 不形成结论");
  expect((screen.getByLabelText("研究问题") as HTMLTextAreaElement).value).toBe("分析风险情况");
  expect(fetchMock.mock.calls.filter(([path]) => path.endsWith("/agent/query"))).toHaveLength(1);
});

