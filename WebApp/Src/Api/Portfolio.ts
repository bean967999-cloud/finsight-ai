import type { MarketPriceSelection } from "./Risk";

export interface PortfolioRequest {
  positions: { selection: MarketPriceSelection; weight: number }[];
  trading_days_per_year: number;
}

export interface PortfolioReport {
  portfolio: {
    tickers: string[];
    weights: number[];
    adjustment_type: string;
    aligned_observations: number;
    trading_days_per_year: number;
    returns: { period_start: string; period_end: string; value: number }[];
    correlation_matrix: (number | null)[][];
    annualized_mean_return: number;
    annualized_volatility: number;
    risk_contributions: {
      ticker: string;
      annualized_volatility_contribution: number;
      share_of_portfolio_volatility: number | null;
    }[];
  };
  sources: [string, string, number][];
  warnings: string[];
}

export function validatePortfolio(input: PortfolioRequest): string | null {
  if (input.positions.length < 1 || input.positions.length > 30) return "组合需要 1 至 30 个资产。";
  if (new Set(input.positions.map((item) => item.selection.ticker)).size !== input.positions.length) return "资产代码不能重复。";
  if (input.positions.some((item) => !Number.isFinite(item.weight) || item.weight < 0 || item.weight > 1)) return "权重需在 0 至 1 之间。";
  if (Math.abs(input.positions.reduce((total, item) => total + item.weight, 0) - 1) > 1e-9) return "权重合计必须为 1；页面不会自动归一化。";
  if (!Number.isInteger(input.trading_days_per_year) || input.trading_days_per_year < 1 || input.trading_days_per_year > 366) return "年交易日数需为 1 至 366。";
  for (const { selection } of input.positions) {
    if (![selection.exchange, selection.ticker, selection.source_code, selection.adjustment_type].every((value) => value.trim())) return "交易所、资产代码、数据源和复权方式均必填。";
    if (!Number.isInteger(selection.data_version) || selection.data_version < 1) return "数据版本需为正整数。";
    if (!selection.start_date || !selection.end_date || selection.start_date > selection.end_date) return "起止日期无效。";
  }
  return null;
}
