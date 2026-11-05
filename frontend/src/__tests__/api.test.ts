import { apiGet, apiSend, ApiError } from "../api";
import { jsonResponse, mockFetch } from "../test-utils";

describe("api", () => {
  it("api_adds_csrf_header", async () => {
    const f = mockFetch({ "POST /api/x": () => jsonResponse({ ok: true }) });
    await apiSend("POST", "/api/x", { a: 1 });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Requested-With")).toBe("mail-pilot");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
  });

  it("api_redirects_on_401", async () => {
    mockFetch({ "GET /api/x": () => jsonResponse({ detail: "Non authentifié" }, 401) });
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/box/all", assign });
    await expect(apiGet("/api/x")).rejects.toBeInstanceOf(ApiError);
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("does_not_redirect_on_401_when_already_on_login", async () => {
    mockFetch({ "POST /api/auth/login": () => jsonResponse({ detail: "Identifiants incorrects" }, 401) });
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/login", assign });
    await expect(apiSend("POST", "/api/auth/login", {})).rejects.toMatchObject({
      status: 401,
      detail: "Identifiants incorrects",
    });
    expect(assign).not.toHaveBeenCalled();
  });

  it("formats_422_detail_list", async () => {
    mockFetch({
      "POST /api/x": () => jsonResponse({ detail: [{ loc: ["body", "password"], msg: "too short", type: "x" }] }, 422),
    });
    await expect(apiSend("POST", "/api/x")).rejects.toMatchObject({ status: 422, detail: "too short" });
  });

  it("returns_undefined_on_204", async () => {
    mockFetch({ "POST /api/auth/logout": () => jsonResponse(null, 204) });
    await expect(apiSend("POST", "/api/auth/logout")).resolves.toBeUndefined();
  });
});
