import { resolveNotificationUrl } from "../notificationUrl";

const o = "https://mail.example";
describe("resolveNotificationUrl", () => {
  it("keeps same-origin paths", () => {
    expect(resolveNotificationUrl("/box/all/inbox?m=3", o)).toBe(`${o}/box/all/inbox?m=3`);
    expect(resolveNotificationUrl(`${o}/x`, o)).toBe(`${o}/x`);
  });
  it("falls back to home for cross-origin, missing or invalid", () => {
    expect(resolveNotificationUrl("https://evil.test/p", o)).toBe(`${o}/`);
    expect(resolveNotificationUrl("//evil.test/p", o)).toBe(`${o}/`);
    expect(resolveNotificationUrl("javascript:alert(1)", o)).toBe(`${o}/`);
    expect(resolveNotificationUrl(undefined, o)).toBe(`${o}/`);
    expect(resolveNotificationUrl("http://[", o)).toBe(`${o}/`);
  });
});
