// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ErrorNotice, TechnicalDetails, TechnicalValue, workspaceLabel } from "./TechnicalDetails";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("keeps the complete value inside a closed native disclosure and only copies on request", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const full = "12345678-1234-4234-8234-123456789abc";
  render(<TechnicalDetails><TechnicalValue name="请求编号" value={full} /></TechnicalDetails>);
  const details = screen.getByText(full).closest("details");
  expect(details?.hasAttribute("open")).toBe(false);
  expect(details?.querySelector("summary")?.textContent).toBe("技术详情");
  expect(writeText).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "复制请求编号", hidden: true }));
  await screen.findByText("已复制");
  expect(writeText).toHaveBeenCalledWith(full);
});
it("reports clipboard failure without a false success", async () => {
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
  render(<TechnicalValue name="流程编号" value="full-thread-id" />);
  fireEvent.click(screen.getByRole("button", { name: "复制流程编号" }));
  await screen.findByText("复制失败，请手动选择并复制编号。");
  expect(screen.queryByText("已复制")).toBeNull();
});
it("clears stale copied feedback when the value changes", async () => {
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  const { rerender } = render(<TechnicalValue name="编号" value="old-value" />);
  fireEvent.click(screen.getByRole("button", { name: "复制编号" }));
  await screen.findByText("已复制");
  rerender(<TechnicalValue name="编号" value="new-value" />);
  expect(screen.queryByText("已复制")).toBeNull();
});
it("does not offer to copy missing values", () => {
  render(<TechnicalValue name="编号" value={null} />);
  expect(screen.getByText("未记录")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
it("uses neutral workspace identifiers, not a fabricated real name", () => {
  expect(workspaceLabel("12345678-1234-4234-8234-123456789abc")).toBe("工作空间 12345678…9abc");
  expect(workspaceLabel("short-id")).toBe("工作空间 short-id");
});
it("keeps the error visible and moves only its request ID to diagnostics", () => {
  render(<ErrorNotice message="请求失败。 请求编号：full-request-id" />);
  expect(screen.getByRole("alert").textContent).toBe("请求失败。");
  expect(screen.getByText("full-request-id").closest("details")).toBeTruthy();
});
it("preserves errors that do not have an identifier", () => {
  render(<ErrorNotice message="没有权限访问该资源。" />);
  expect(screen.getByRole("alert").textContent).toBe("没有权限访问该资源。");
  expect(screen.queryByText("错误诊断")).toBeNull();
});
