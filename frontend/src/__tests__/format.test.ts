import { formatFull, formatRowDate, formatSince } from "../format";

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

describe("formatSince", () => {
  const now = new Date("2026-11-10T12:00:00Z");
  it("formats today, yesterday, weekday and older dates", () => {
    expect(formatSince("2026-11-10T07:12:00Z", now)).toBe("08:12");
    expect(formatSince("2026-11-09T21:10:00Z", now)).toBe("hier 22:10");
    expect(formatSince("2026-11-07T07:00:00Z", now)).toBe("samedi 08:00");
    expect(formatSince("2026-10-01T07:00:00Z", now)).toBe("01/10 09:00");
    expect(formatSince(null, now)).toBe("");
  });
});
