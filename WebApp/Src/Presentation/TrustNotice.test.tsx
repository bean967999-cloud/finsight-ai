// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AnswerMethod, RiskGlossary, TrustNotice } from "./TrustNotice";
import type { GenerationInfo } from "../Api/Research";

afterEach(cleanup);
it("keeps the boundary visible and only folds the detailed explanation", () => {
  render(<TrustNotice summary="不构成投资建议">详细口径</TrustNotice>);
  expect(screen.getByText("不构成投资建议").closest("details")).toBeNull();
  expect(screen.getByText("详细口径").closest("details")?.hasAttribute("open")).toBe(false);
});
it.each([
  ["local", "回答方式：本地核验答案，未发送外部请求"],
  ["generated", "回答方式：模型选择已核验证据，本地模板呈现（非自由生成）"],
  ["fallback", "回答方式：外部调用未形成合格结果，已回退至本地核验答案"],
])("shows the saved %s mode without inferring it from approval", (mode, expected) => {
  render(<AnswerMethod generation={{ mode, reason: "fixture", attempts: 1 } as GenerationInfo} />);
  expect(screen.getByText(expected)).toBeTruthy();
});
it("does not infer a local answer or successful model call for old records", () => {
  render(<AnswerMethod />);
  expect(screen.getByText(/历史结果未记录调用方式/)).toBeTruthy();
  expect(screen.queryByText(/未发送外部请求/)).toBeNull();
});
it("does not treat unknown future modes as local", () => {
  render(<AnswerMethod generation={{ mode: "future", reason: "fixture", attempts: 0 } as unknown as GenerationInfo} />);
  expect(screen.getByText(/未识别的调用状态/)).toBeTruthy();
});
it("keeps financial limits visible and defines VaR without promising a loss ceiling", () => {
  render(<RiskGlossary />);
  expect(screen.getByText(/不保证未来损失上限/).closest("details")).toBeNull();
  expect(screen.getByText(/不是最坏损失/)).toBeTruthy();
  expect(screen.getByText(/不是货币损失/)).toBeTruthy();
});
