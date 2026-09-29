import { describe, expect, it } from "vitest";
import { citationLabel } from "./Evidence";

describe("citation status", () => {
  it("never presents pending evidence as verified", () => {
    expect(citationLabel("pending")).toContain("待核验");
    expect(citationLabel("verified")).toBe("已核验");
    expect(citationLabel("rejected")).toBe("核验未通过");
  });
});
