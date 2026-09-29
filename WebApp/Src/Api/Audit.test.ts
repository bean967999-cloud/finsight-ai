import { expect, it } from "vitest";
import { auditOutcome } from "./Audit";

it("does not present started or denied operations as success", () => {
  expect(auditOutcome("started")).toContain("尚未记录完成");
  expect(auditOutcome("denied")).toBe("访问被拒绝");
  expect(auditOutcome("succeeded")).toBe("操作成功");
});
