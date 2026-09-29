import { expect, it } from "vitest";
import { validatePortfolio, type PortfolioRequest } from "./Portfolio";

const selection = { exchange: "SSE", ticker: "A", source_code: "fixture", adjustment_type: "none", data_version: 1, start_date: "2024-01-01", end_date: "2024-02-01" };
const input: PortfolioRequest = { positions: [{ selection, weight: 0.5 }, { selection: { ...selection, ticker: "B" }, weight: 0.5 }], trading_days_per_year: 252 };

it("validates the exact portfolio without silently changing weights", () => {
  expect(validatePortfolio(input)).toBeNull();
  expect(validatePortfolio({ ...input, positions: [{ selection, weight: 0.4 }] })).toContain("权重合计");
  expect(validatePortfolio({ ...input, positions: [{ selection, weight: 0.5 }, { selection, weight: 0.5 }] })).toContain("不能重复");
});
