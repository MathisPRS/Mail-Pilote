import { parsePushPayload } from "../pushPayload";

describe("parsePushPayload", () => {
  it("reads the url from data.url (backend payload)", () => {
    expect(parsePushPayload('{"title":"T","body":"B","data":{"url":"/mail/3"}}')).toEqual({
      title: "T",
      body: "B",
      url: "/mail/3",
    });
  });
  it("accepts a top-level url (legacy payload)", () => {
    expect(parsePushPayload('{"title":"T","url":"/mail/4"}').url).toBe("/mail/4");
  });
  it("falls back to defaults for plain text or empty payloads", () => {
    expect(parsePushPayload("bonjour")).toEqual({ title: "Mail Pilot", body: "bonjour", url: "/" });
    expect(parsePushPayload(null)).toEqual({ title: "Mail Pilot", body: "", url: "/" });
    expect(parsePushPayload('{"data":{"url":42}}').url).toBe("/");
  });
});
