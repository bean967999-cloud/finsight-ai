import { ErrorNotice } from "../Presentation/TechnicalDetails";
import { label, explanation } from "../Presentation/Labels";
import { usePageState } from "../Auth/PageState";
import { useState, type FormEvent } from "react";
import { ApiError, requestFailure } from "../Api/Client";
import { percent, type MarketPriceSelection } from "../Api/Risk";
import { validatePortfolio, type PortfolioReport, type PortfolioRequest } from "../Api/Portfolio";
import { useSession } from "../Auth/Session";
import { TrustNotice } from "../Presentation/TrustNotice";

export function PortfolioRiskPanel() {
  const { request } = useSession();
  const [selection, setSelection] = usePageState<Omit<MarketPriceSelection, "ticker">>("PortfolioRiskPanel.selection", {
    exchange: "", source_code: "", adjustment_type: "", data_version: 1, start_date: "", end_date: "",
  });
  const [positions, setPositions] = usePageState("PortfolioRiskPanel.positions", [{ ticker: "", weight: 0.5 }, { ticker: "", weight: 0.5 }]);
  const [days, setDays] = usePageState("PortfolioRiskPanel.days", 252);
  const [report, setReport] = usePageState<PortfolioReport | null>("PortfolioRiskPanel.report", null);
  const [error, setError] = usePageState("PortfolioRiskPanel.error", "");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setReport(null); setError("");
    const payload: PortfolioRequest = {
      positions: positions.map((item) => ({ selection: { ...selection, ticker: item.ticker.trim() }, weight: item.weight })),
      trading_days_per_year: days,
    };
    const invalid = validatePortfolio(payload);
    if (invalid) { setError(invalid); return; }
    setBusy(true);
    try { setReport(await request<PortfolioReport>("/api/v1/risk/portfolio-report/from-db", "POST", payload)); }
    catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404 ? "没有匹配的组合行情，请核对标的和数据来源。"
        : requestFailure(failure, "组合报告请求失败。"));
    } finally { setBusy(false); }
  }

  const result = report?.portfolio;
  return <section className="page-card evaluation-section" style={{ marginTop: 22 }}>
    <h2>组合风险</h2>
    <TrustNotice summary="组合风险取决于权重和资产共同涨跌关系；低相关性不保证未来没有损失。" title="组合计算口径">
      <p>相关系数描述所选历史样本中的共同变化。风险贡献度反映各资产对组合波动的贡献，不是收益贡献或最大损失分配。</p>
      <p>先对齐收益窗口，再按权重计算；假设每个观察期恢复目标权重，未计交易成本。当前组合接口不返回VaR/CVaR或最大回撤。</p>
    </TrustNotice>
    <p className="muted">本表单的资产共用交易所、来源、版本、复权和日期范围。长仓权重合计为 1，不自动调整用户输入。</p>
    <form className="research-form risk-form" onSubmit={submit}>
      {(["exchange", "source_code", "adjustment_type", "start_date", "end_date"] as const).map((field) => {
        const labels = { exchange: "组合交易所", source_code: "组合数据源", adjustment_type: "组合复权方式", start_date: "组合开始日期", end_date: "组合结束日期" };
        return <label key={field}>{labels[field]}<input required type={field.endsWith("date") ? "date" : "text"}
          value={selection[field]} onChange={(event) => setSelection({ ...selection, [field]: event.target.value })} /></label>;
      })}
      <label>组合数据版本<input type="number" min="1" value={selection.data_version}
        onChange={(event) => setSelection({ ...selection, data_version: Number(event.target.value) })} /></label>
      <label>组合年交易日数<input type="number" min="1" max="366" value={days} onChange={(event) => setDays(Number(event.target.value))} /></label>
      {positions.map((item, index) => <div className="research-form" key={index}>
        <label>资产 {index + 1} 代码<input required value={item.ticker} onChange={(event) => setPositions(positions.map((position, i) => i === index ? { ...position, ticker: event.target.value } : position))} /></label>
        <label>资产 {index + 1} 权重<input type="number" min="0" max="1" step="any" value={item.weight}
          onChange={(event) => setPositions(positions.map((position, i) => i === index ? { ...position, weight: Number(event.target.value) } : position))} /></label>
        <button type="button" disabled={positions.length <= 1 || busy} onClick={() => setPositions(positions.filter((_, i) => i !== index))}>移除资产 {index + 1}</button>
      </div>)}
      <button type="button" disabled={positions.length >= 30 || busy} onClick={() => setPositions([...positions, { ticker: "", weight: 0 }])}>添加资产</button>
      <button type="submit" disabled={busy}>{busy ? "正在计算组合…" : "计算组合风险"}</button>
      {error && <ErrorNotice message={error} />}
    </form>
    {result && <>
      <p>对齐收益窗口：{result.aligned_observations} 个 · {result.returns[0]?.period_start} 至 {result.returns.at(-1)?.period_end}</p>
      <div className="metric-grid">
        <div><span>年化算术平均收益（非累计收益）</span><strong>{percent(result.annualized_mean_return)}</strong></div>
        <div><span>组合年化波动率</span><strong>{percent(result.annualized_volatility)}</strong></div>
        <div><span>复权口径</span><strong>{label("adjustment", result.adjustment_type)}</strong></div>
      </div>
      <h3>风险贡献度</h3>
      <div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>资产</th><th>权重</th><th>波动贡献（百分点）</th><th>贡献占比</th></tr></thead>
        <tbody>{result.risk_contributions.map((item, index) => <tr key={item.ticker}><td>{item.ticker}</td><td>{percent(result.weights[index])}</td>
          <td>{(item.annualized_volatility_contribution * 100).toFixed(3)}</td><td>{item.share_of_portfolio_volatility === null ? "不可计算" : percent(item.share_of_portfolio_volatility)}</td></tr>)}</tbody></table></div>
      <h3>收益相关系数</h3>
      <div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>资产</th>{result.tickers.map((ticker) => <th key={ticker}>{ticker}</th>)}</tr></thead>
        <tbody>{result.correlation_matrix.map((row, index) => <tr key={result.tickers[index]}><th>{result.tickers[index]}</th>{row.map((value, column) => <td key={column}>{value === null ? "不可计算" : value.toFixed(3)}</td>)}</tr>)}</tbody></table></div>
      <p>来源：{report?.sources.map(([ticker, source, version]) => `${ticker} / ${source} / v${version}`).join("；")}</p>
      <ul>{report?.warnings.map((warning) => <li key={warning}>{explanation(warning)}</li>)}</ul>
    </>}
    <p className="muted">当前组合接口不返回 VaR/CVaR 或最大回撤，本页不展示这些指标。模型假设每个观察期恢复目标权重，未计交易成本；相关性低不保证未来没有损失。</p>
  </section>;
}
