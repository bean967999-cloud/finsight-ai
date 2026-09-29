import { describe, expect, it } from "vitest";
import { evaluatedCount, rate } from "./Evaluation";

describe("evaluation display", () => {
  it("keeps missing scores distinct from zero scores", () => {
    expect(rate(null)).toBe("未运行");
    expect(rate(0)).toBe("0.0%");
  });

  it("shows both passed and total counts", () => {
    expect(evaluatedCount(3, 4)).toBe("3 / 4");
  });
});
