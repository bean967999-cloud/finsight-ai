import { describe, expect, it } from "vitest";
import { generationLabel, parsePrices, resultLabel, type ResearchResponse } from "./Research";

const result: ResearchResponse = {
  thread_id: null, review_pending: false, review_request: null,
  intent: "risk_analysis", answer: "result", answer_status: "answered",
  limitations: [], risk_metrics: null, evidence: [],
};

describe("research form helpers", () => {
  it("distinguishes local answers, model selection and fallback", () => {
    expect(generationLabel(result)).toBeNull();
    expect(generationLabel({ ...result, generation: { mode: "local", reason: "disabled", attempts: 0 } })).toContain("未发送外部请求");
    expect(generationLabel({ ...result, generation: { mode: "generated", reason: "verified_evidence_selection", attempts: 1 } })).toContain("非自由生成");
    expect(generationLabel({ ...result, generation: { mode: "fallback", reason: "provider_failed", attempts: 2 } })).toContain("回退");
  });
  it("parses valid prices and leaves empty input absent", () => {
    expect(parsePrices("10, 10.5，11")).toEqual([10, 10.5, 11]);
    expect(parsePrices("  ")).toBeUndefined();
  });

  it("rejects incomplete or invalid prices before a request", () => {
    expect(() => parsePrices("1,2")).toThrow();
    expect(() => parsePrices("1,0,3")).toThrow();
    expect(() => parsePrices("1,NaN,3")).toThrow();
  });

  it("prioritizes review and insufficient evidence over a success label", () => {
    expect(resultLabel({ ...result, review_pending: true })).toContain("等待人工确认");
    expect(resultLabel({ ...result, answer_status: "insufficient_evidence" })).toContain("证据不足");
  });
});
