import { describe, expect, it } from "vitest";
import { cumulativeReturn, percent, validateRiskRequest, type AssetRiskReport, type DatabaseAssetRiskRequest } from "./Risk";

const request: DatabaseAssetRiskRequest = {
  asset: {
    exchange: "SSE", ticker: "600000", source_code: "market_source",
    adjustment_type: "none", data_version: 1,
    start_date: "2024-01-01", end_date: "2024-12-31",
  },
  confidence: 0.95, holding_period: 1, minimum_observations: 20,
  annual_risk_free_rate: 0, trading_days_per_year: 252,
};

describe("risk display and request validation", () => {
  it("rejects reversed dates and invalid confidence", () => {
    expect(validateRiskRequest(request)).toBeNull();
    expect(validateRiskRequest({ ...request, asset: { ...request.asset, start_date: "2025-01-01" } })).toContain("日期");
    expect(validateRiskRequest({ ...request, confidence: 1 })).toContain("置信水平");
  });

  it("derives return only from the returned wealth index", () => {
    const report = { drawdown: { curve: [{ trade_date: "2024-12-31", wealth_index: 1.12, drawdown: 0 }] } } as AssetRiskReport;
    expect(cumulativeReturn(report)).toBeCloseTo(0.12);
    expect(percent(-0.1)).toBe("-10.00%");
  });
});
