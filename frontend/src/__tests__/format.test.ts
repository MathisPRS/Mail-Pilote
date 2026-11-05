import { formatFull, formatRowDate } from "../format";

describe("dates absentes ou invalides", () => {
  it("never renders Invalid Date", () => {
    for (const v of [null, undefined, "", "pas une date"]) {
      expect(formatRowDate(v)).toBe("");
      expect(formatFull(v)).toBe("");
    }
  });
  it("still formats valid dates", () => {
    expect(formatRowDate("2026-11-05T07:12:00Z", new Date("2026-11-05T12:00:00Z"))).toBe("08:12");
    expect(formatFull("2026-11-05T07:12:00Z")).toContain("2026");
  });
});
