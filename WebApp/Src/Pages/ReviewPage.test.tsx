import { PageStateProvider } from "../Auth/PageState";
// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReviewPage } from "./ReviewPage";

const state = vi.hoisted(() => ({ role: "reviewer", request: vi.fn() }));
vi.mock("../Auth/Session", () => ({ useSession: () => ({ principal: { memberships: [{ role: state.role }] }, request: state.request }) }));
afterEach(() => { cleanup(); state.request.mockReset(); });
const flow = { thread_id: "test-thread", phase: "awaiting_review", answer_status: "answered", answer: "test saved answer", citations: [], limitations: [], review_outcome: null };

it.each(["generated", "fallback", "local"])("renders the saved %s answer mode independently of a confirmed review", async mode => {
  state.role = "reviewer";
  state.request.mockResolvedValue({ ...flow, phase: "finished", generation: { mode, reason: "fixture", attempts: 1 },
    review_outcome: { choice: "confirmed", note: "checked" } });
  render(<MemoryRouter><PageStateProvider><ReviewPage /></PageStateProvider></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("待审核流程编号"), { target: { value: "test-thread" } });
  fireEvent.click(screen.getByRole("button", { name: "读取审核流程" }));
  await screen.findByText("审核结果：已确认 · checked");
  const expected = mode === "generated" ? "模型选择已核验证据" : mode === "fallback" ? "已回退至本地核验答案" : "未发送外部请求";
  expect(screen.getByText(new RegExp(expected))).toBeTruthy();
  expect(state.request).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "确认本次审核" })).toBeNull();
});

it("reads saved content and rejects an unexplained rejection", async () => {
  state.role = "reviewer"; state.request.mockResolvedValue(flow);
  render(<MemoryRouter><PageStateProvider><ReviewPage /></PageStateProvider></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("待审核流程编号"), { target: { value: "test-thread" } });
  fireEvent.click(screen.getByRole("button", { name: "读取审核流程" }));
  await screen.findByText("test saved answer");
  fireEvent.click(screen.getByRole("button", { name: "驳回本次审核" }));
  await screen.findByText("驳回必须说明原因。");
  expect(state.request).toHaveBeenCalledTimes(1);
});

it("confirms then rereads authoritative finished content", async () => {
  state.role = "reviewer";
  state.request.mockResolvedValueOnce(flow).mockResolvedValueOnce({}).mockResolvedValueOnce({ ...flow, phase: "finished", review_outcome: { choice: "confirmed", note: "checked" } });
  render(<MemoryRouter><PageStateProvider><ReviewPage /></PageStateProvider></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("待审核流程编号"), { target: { value: "test-thread" } });
  fireEvent.click(screen.getByRole("button", { name: "读取审核流程" }));
  await screen.findByText("test saved answer");
  fireEvent.change(screen.getByLabelText("审核说明"), { target: { value: "checked" } });
  fireEvent.click(screen.getByRole("button", { name: "确认本次审核" }));
  await screen.findByText("审核结果：已确认 · checked");
  expect(state.request).toHaveBeenCalledWith("/api/v1/agent/threads/test-thread/review", "POST", { choice: "confirmed", note: "checked" });
  expect(screen.queryByRole("button", { name: "确认本次审核" })).toBeNull();
});

it("translates verification but preserves the original disclosure quote", async () => {
  state.role = "reviewer";
  const quote = "total dividends of HK$6.50 per share for 2023";
  state.request.mockResolvedValue({ ...flow, citations: [{
    citation_id: "C1", status: "verified", quoted_text: quote,
    verification_reason: "quote is source-anchored and every claim number matches in value and unit",
    evidence: { candidate: { document_title: "Original disclosure", page_start: 1 } },
  }] });
  render(<MemoryRouter><PageStateProvider><ReviewPage /></PageStateProvider></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("待审核流程编号"), { target: { value: "test-thread" } });
  fireEvent.click(screen.getByRole("button", { name: "读取审核流程" }));
  await screen.findByText(quote);
  expect(screen.getByText("C1 · 原文锚定已核验")).toBeTruthy();
  expect(screen.getByText("引用原句已定位到来源片段，结论中的数值与单位核验一致。")).toBeTruthy();
  expect(screen.getByText("流程状态：等待人工审核 · 答案状态：已回答")).toBeTruthy();
  expect(state.request).toHaveBeenCalledTimes(1);
});
