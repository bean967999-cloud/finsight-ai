import { describe, expect, it } from "vitest";
import { booleanLabel, explanation, label, type LabelCategory } from "./Labels";

describe("display-only Chinese labels", () => {
  it.each<[LabelCategory, string, string]>([
    ["role", "researcher", "研究员"], ["role", "workspace_admin", "工作空间管理员"],
    ["intent", "document_research", "文档研究"], ["tool", "document_search", "文档检索"],
    ["toolStatus", "failed", "执行失败"], ["answer", "insufficient_evidence", "证据不足"],
    ["phase", "awaiting_review", "等待人工审核"], ["review", "rejected", "已驳回"],
    ["citation", "rejected", "核验未通过"], ["job", "retry_wait", "等待重试"],
    ["event", "tool_completed", "工具执行结束"], ["evaluation", "not_run", "尚未运行"],
    ["adjustment", "none", "未复权"], ["metric", "historical_var", "历史VaR"],
    ["source", "synthetic_fixture", "固定合成样例"],
  ])("maps %s/%s without changing the underlying value", (category, value, expected) => {
    expect(label(category, value)).toBe(expected);
    expect(value).not.toBe(expected);
  });

  it("does not treat event completion as success", () => {
    expect(label("event", "tool_completed")).not.toContain("成功");
    expect(label("toolStatus", "unavailable")).toBe("暂不可用");
  });
  it("preserves unknown codes and distinguishes missing from false", () => {
    expect(label("job", "future_status")).toBe("未识别状态（future_status）");
    expect(label("phase", null)).toBe("未记录");
    expect(booleanLabel(null)).toBe("未记录");
    expect(booleanLabel(false)).toBe("否");
    expect(booleanLabel(true)).toBe("是");
  });
  it.each([
    "Trading-calendar gaps have not been verified.",
    "Historical risk estimates do not bound future losses.",
    "Beta was not calculated because no benchmark was supplied.",
    "Prices and source labels were supplied by the caller and have not been verified.",
    "Currency compatibility has not been verified.",
    "Target weights are restored each observed period; trading costs are excluded.",
  ])("keeps the risk restriction in Chinese: %s", value => {
    expect(explanation(value)).toMatch(/[\u3400-\u9fff]/);
    expect(explanation(value)).not.toContain("尚未映射");
  });
  it("preserves failed numeric comparisons and dynamic values", () => {
    expect(explanation("claim numbers or units are not supported by the quote: 9.99%"))
      .toBe("结论中的部分数值或单位缺少该引用支持：9.99%");
    expect(explanation("requested quote is not an exact substring of the source chunk")).toContain("未通过");
    expect(explanation("quote is source-anchored; no numeric claim required numeric comparison")).toContain("未涉及");
  });
  it("keeps unknown narrative restrictions and original Chinese", () => {
    expect(explanation("A new restriction.")).toBe("尚未映射的说明：A new restriction.");
    expect(explanation("不构成投资建议")).toBe("不构成投资建议");
    expect(explanation(null)).toBe("未提供说明");
    expect(explanation("document_search: UnexpectedToolError")).toContain("文档检索：工具执行异常");
  });
});
