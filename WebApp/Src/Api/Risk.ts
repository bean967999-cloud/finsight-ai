export interface MarketPriceSelection {
  exchange: string;
  ticker: string;
  source_code: string;
  adjustment_type: string;
  data_version: number;
  start_date: string;
  end_date: string;
}

export interface DatabaseAssetRiskRequest {
  asset: MarketPriceSelection;
  confidence: number;
  holding_period: number;
  minimum_observations: number;
  annual_risk_free_rate: number;
  trading_days_per_year: number;
}

export interface AssetRiskReport {
  ticker: string;
  adjustment_type: string;
  data_source: string;
  data_version: number;
  price_observations: number;
  start_date: string;
  end_date: string;
  volatility: {
    return_observations: number;
    trading_days_per_year: number;
    daily_volatility: number;
    annualized_volatility: number;
  };
  drawdown: {
    curve: { trade_date: string; wealth_index: number; drawdown: number }[];
    max_drawdown: number;
    peak_date: string | null;
    trough_date: string | null;
  };
  tail_risk: {
    confidence: number;
    holding_period: number;
    observations: number;
    tail_observations: number;
    value_at_risk: number;
    conditional_value_at_risk: number;
    first_window_start: string;
    last_window_end: string;
  };
  sharpe: { sharpe_ratio: number | null };
  units: { returns_and_volatility: "fraction" };
  warnings: string[];
}

export function validateRiskRequest(request: DatabaseAssetRiskRequest): string | null {
  const selection = request.asset;
  if (!selection.exchange.trim() || !selection.ticker.trim() ||
      !selection.source_code.trim() || !selection.adjustment_type.trim()) {
    return "交易所、代码、数据源和复权方式均必填。";
  }
  if (!Number.isInteger(selection.data_version) || selection.data_version < 1) {
    return "数据版本必须是正整数。";
  }
  if (!selection.start_date || !selection.end_date || selection.start_date > selection.end_date) {
    return "请选择有效的起止日期，且开始日期不能晚于结束日期。";
  }
  if (!(request.confidence > 0.5 && request.confidence < 1)) {
    return "置信水平必须大于 0.5 且小于 1。";
  }
  if (!Number.isInteger(request.holding_period) || request.holding_period < 1 || request.holding_period > 252) {
    return "持有期必须是 1 至 252 个观察间隔。";
  }
  if (!Number.isInteger(request.minimum_observations) ||
      request.minimum_observations < 2 || request.minimum_observations > 5000) {
    return "最少样本数必须是 2 至 5000。";
  }
  if (!Number.isFinite(request.annual_risk_free_rate) || request.annual_risk_free_rate <= -1) {
    return "年化无风险利率必须大于 -1。";
  }
  if (!Number.isInteger(request.trading_days_per_year) ||
      request.trading_days_per_year < 1 || request.trading_days_per_year > 366) {
    return "年交易日数必须是 1 至 366。";
  }
  return null;
}

export function cumulativeReturn(report: AssetRiskReport): number | null {
  const last = report.drawdown.curve.at(-1);
  return last ? last.wealth_index - 1 : null;
}

export function percent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}
