import { TechnicalDetails, TechnicalValue, ErrorNotice } from "../Presentation/TechnicalDetails";
import { label, explanation } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useState, type FormEvent } from "react";
import { ApiError } from "../Api/Client";
import { cumulativeReturn, percent, validateRiskRequest,
  type AssetRiskReport, type DatabaseAssetRiskRequest } from "../Api/Risk";
import { useSession } from "../Auth/Session";
import { DrawdownChart } from "./DrawdownChart";
import { PortfolioRiskPanel } from "./PortfolioRiskPanel";
import { RiskGlossary } from "../Presentation/TrustNotice";

const initial: DatabaseAssetRiskRequest = {
  asset: { exchange: "", ticker: "", source_code: "", adjustment_type: "", data_version: 1,
    start_date: "", end_date: "" },
  confidence: 0.95,
  holding_period: 1,
  minimum_observations: 20,
  annual_risk_free_rate: 0,
  trading_days_per_year: 252,
};

export function RiskPage() {
  const { request } = useSession();
  const [input, setInput] = usePageState<DatabaseAssetRiskRequest>("RiskPage.input", initial);
  const [report, setReport] = usePageState<AssetRiskReport | null>("RiskPage.report", null);
  const [requestId, setRequestId] = usePageState<string | null>("RiskPage.requestId", null);
  const [error, setError] = usePageState("RiskPage.error", "");
  const [busy, setBusy] = useState(false);
  const returnValue = report ? cumulativeReturn(report) : null;

  function setAsset(field: keyof DatabaseAssetRiskRequest["asset"], value: string | number) {
    setInput((current) => ({ ...current, asset: { ...current.asset, [field]: value } }));
  }

  function setSetting(field: Exclude<keyof DatabaseAssetRiskRequest, "asset">, value: number) {
    setInput((current) => ({ ...current, [field]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setReport(null);
    setRequestId(null);
    setError("");
    const validationError = validateRiskRequest(input);
    if (validationError) { setError(validationError); return; }
    setBusy(true);
    try {
      const received = await request<AssetRiskReport>(
        "/api/v1/risk/asset-report/from-db", "POST", input, undefined, setRequestId,
      );
      setReport(received);
    } catch (failure) {
      const message = failure instanceof ApiError && failure.status === 404
        ? "数据库中没有匹配这一数据源、版本、标的及日期区间的价格。"
        : failure instanceof Error ? failure.message : "风险报告请求失败。";
      const id = failure instanceof ApiError && failure.requestId ? ` 请求编号：${failure.requestId}` : "";
      setError(message + id);
    } finally {
      setBusy(false);
    }
  }

  return <div className="risk-layout">
    <section className="page-card">
      <h1>单资产风险看板</h1>
      <p className="muted">使用已入库行情计算风险，请选择匹配的数据源、版本、复权方式与日期范围。</p>
      <p className="muted">平台公共行情：后端要求有效且启用的登录身份，不按工作空间划分读取权限；私有文档仍独立校验空间范围。</p>
      <form className="research-form risk-form" onSubmit={submit}>
        <label>交易所<input value={input.asset.exchange} maxLength={16} required
          onChange={(event) => setAsset("exchange", event.target.value)} placeholder="例如 SSE；请与数据库记录一致" /></label>
        <label>资产代码<input value={input.asset.ticker} maxLength={32} required
          onChange={(event) => setAsset("ticker", event.target.value)} /></label>
        <label>数据源代码<input value={input.asset.source_code} maxLength={50} required
          onChange={(event) => setAsset("source_code", event.target.value)} /></label>
        <label>复权方式<input value={input.asset.adjustment_type} maxLength={16} required
          onChange={(event) => setAsset("adjustment_type", event.target.value)} /></label>
        <label>数据版本<input type="number" min="1" step="1" value={input.asset.data_version}
          onChange={(event) => setAsset("data_version", Number(event.target.value))} /></label>
        <label>开始日期<input type="date" value={input.asset.start_date} required
          onChange={(event) => setAsset("start_date", event.target.value)} /></label>
        <label>结束日期<input type="date" value={input.asset.end_date} required
          onChange={(event) => setAsset("end_date", event.target.value)} /></label>
        <label>置信水平<input type="number" min="0.51" max="0.99" step="0.01"
          value={input.confidence} onChange={(event) => setSetting("confidence", Number(event.target.value))} /></label>
        <label>持有期（观察间隔）<input type="number" min="1" max="252" step="1"
          value={input.holding_period} onChange={(event) => setSetting("holding_period", Number(event.target.value))} /></label>
        <label>最少收益样本数<input type="number" min="2" max="5000" step="1"
          value={input.minimum_observations} onChange={(event) => setSetting("minimum_observations", Number(event.target.value))} /></label>
        <label>年化无风险利率（小数）<input type="number" min="-0.99" step="0.001"
          value={input.annual_risk_free_rate} onChange={(event) => setSetting("annual_risk_free_rate", Number(event.target.value))} /></label>
        <label>年交易日数<input type="number" min="1" max="366" step="1"
          value={input.trading_days_per_year} onChange={(event) => setSetting("trading_days_per_year", Number(event.target.value))} /></label>
        <button type="submit" disabled={busy}>{busy ? "正在计算…" : "读取并计算风险报告"}</button>
        {error && <ErrorNotice message={error} />}
      </form>
    </section>
    <section className="page-card risk-report" aria-live="polite">
      <h2>风险报告</h2>
      <RiskGlossary />
      {!report && <p className="muted">尚无本次报告。请使用数据库中真实存在的价格序列。</p>}
      {report && <>
        <p className="muted">{report.ticker} · {report.start_date} 至 {report.end_date}
          · 价格点 {report.price_observations} 个 · 收益样本 {report.volatility.return_observations} 个</p>
        <p className="muted">来源 {report.data_source} · 版本 {report.data_version}
          · 复权 {label("adjustment", report.adjustment_type)}</p>
        <TechnicalDetails><TechnicalValue name="风险请求编号" value={requestId} /></TechnicalDetails>
        <div className="metric-grid">
          <div><span>区间累计收益（由净值曲线末值推导）</span><strong>{returnValue === null ? "无" : percent(returnValue)}</strong></div>
          <div><span>年化波动率</span><strong>{percent(report.volatility.annualized_volatility)}</strong></div>
          <div><span>最大回撤</span><strong>{percent(report.drawdown.max_drawdown)}</strong></div>
          <div><span>历史 VaR</span><strong>{percent(report.tail_risk.value_at_risk)}</strong></div>
          <div><span>历史 CVaR</span><strong>{percent(report.tail_risk.conditional_value_at_risk)}</strong></div>
          <div><span>夏普比率</span><strong>{report.sharpe.sharpe_ratio === null ? "不可计算" : report.sharpe.sharpe_ratio.toFixed(3)}</strong></div>
        </div>
        <p className="muted">尾部口径：置信水平 {percent(report.tail_risk.confidence)}，持有期 {report.tail_risk.holding_period} 个观察间隔，
          收益窗口 {report.tail_risk.observations} 个，尾部样本 {report.tail_risk.tail_observations} 个；
          {report.tail_risk.first_window_start} 至 {report.tail_risk.last_window_end}。</p>
        <h3>历史回撤曲线</h3>
        <DrawdownChart curve={report.drawdown.curve} />
        <p className="muted">最大回撤对应峰值日 {report.drawdown.peak_date ?? "无"}、谷值日 {report.drawdown.trough_date ?? "无"}。</p>
        <h3>报告限制</h3>
        <ul>{report.warnings.map((warning) => <li key={warning}>{explanation(warning)}</li>)}</ul>
        <p className="muted">VaR/CVaR 是样本历史损失比例，不是货币损失，也不是未来损失上限。</p>
      </>}
    </section>
  </div>;
}

export default function RiskDashboard() {
  return <><RiskPage /><PortfolioRiskPanel /></>;
}
