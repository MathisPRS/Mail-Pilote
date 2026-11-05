export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type Method = "POST" | "PUT" | "PATCH" | "DELETE";

function extractDetail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length > 0) {
    const first = d[0] as { msg?: unknown };
    if (typeof first?.msg === "string") return first.msg;
  }
  return `Erreur ${status}`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers = new Headers({ "X-Requested-With": "mail-pilot" });
  const init: RequestInit = { method, headers, credentials: "same-origin" };
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    if (res.status === 401 && window.location.pathname !== "/login") {
      window.location.assign("/login");
    }
    throw new ApiError(res.status, extractDetail(data, res.status));
  }
  return data as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function apiSend<T>(method: Method, path: string, body?: unknown): Promise<T> {
  return request<T>(method, path, body);
}

// --- Auth ---
import type { AuthStatus, SessionUser } from "./types";

export const getAuthStatus = () => apiGet<AuthStatus>("/api/auth/status");
export const authSetup = (b: { username: string; password: string; display_name: string }) =>
  apiSend<{ username: string }>("POST", "/api/auth/setup", b);
export const authLogin = (b: { username: string; password: string }) =>
  apiSend<SessionUser>("POST", "/api/auth/login", b);
export const authLogout = () => apiSend<void>("POST", "/api/auth/logout");
export const getMe = () => apiGet<SessionUser>("/api/auth/me");
