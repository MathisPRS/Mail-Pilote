import { vi } from "vitest";
import { jsonResponse } from "./test-utils";
import type { BoxSummary, Folder, Message, MessageDetail } from "./types";

export function msg(id: number, over: Partial<Message> = {}): Message {
  return {
    id, account_id: 1, account_color: "#D93025", from_name: `Expéditeur ${id}`, from_addr: `e${id}@ex.fr`,
    subject: `Sujet ${id}`, preview: `Aperçu ${id}`, sent_at: "2026-11-05T07:12:00Z", seen: false,
    category: "info", priority: false, reason: null, summary: null, ...over,
  };
}

export const boxes: BoxSummary[] = [
  { id: "all", label: "Toutes les boîtes", email: "Vue unifiée de 2 boîtes", color: "#111317", unread: 5,
    priority: [{ id: 1, label: "TT+", subject: "Ouverture TT+ jeudi", category: "tt" }] },
  { id: 1, label: "Gmail", email: "a@gmail.com", color: "#D93025", unread: 3, priority: [] },
  { id: 2, label: "Outlook", email: "b@outlook.fr", color: "#0F6CBD", unread: 2,
    priority: [{ id: 2, label: "Impôts", subject: "Avis de taxe", category: "important" }] },
];

export const folders: Folder[] = [
  { key: "inbox", role: "inbox", label: "Réception", unread: 5 },
  { key: "sent", role: "sent", label: "Envoyés", unread: 0 },
  { key: "archive", role: "archive", label: "Archives", unread: 0 },
  { key: "trash", role: "trash", label: "Corbeille", unread: 0 },
];

export const inboxMessages: Message[] = [
  msg(1, { subject: "Ouverture TT+ jeudi", category: "tt", priority: true, from_name: "Service RH" }),
  msg(2, { subject: "Avis de taxe foncière", category: "important", priority: true, from_name: "Impôts" }),
  msg(3, { subject: "Relevé disponible", category: "info", from_name: "Banque", seen: true }),
  msg(4, { subject: "Promo ce week-end", category: "pub", from_name: "Promo Mode" }),
];

export function detail(id: number, over: Partial<MessageDetail> = {}): MessageDetail {
  return {
    ...msg(id), body_html: "<p>Bonjour le monde</p>", body_text: "Bonjour le monde", attachments: [],
    open_url: null, ...over,
  };
}

export interface Call { method: string; path: string; query: URLSearchParams; body: unknown }
type Handler = (call: Call) => Response;

/** Simule l'API : clés "METHOD /chemin" (sans query string). Renvoie les appels enregistrés. */
export function mockApi(handlers: Record<string, Handler | object>) {
  const calls: Call[] = [];
  const defaults: Record<string, unknown> = {
    "GET /api/auth/status": { setup_done: true, authenticated: true },
    "GET /api/auth/me": { username: "m", display_name: "Mathis" },
    "GET /api/claude/status": { connected: true, last_ok_at: null, last_error: null, token_set_at: null, expires_at: null, days_left: null, warn_days: 7 },
    "GET /api/runs/latest": { light: null, full: { id: 1, kind: "full", trigger: "schedule", status: "ok", started_at: "2026-11-05T07:00:00Z", finished_at: "2026-11-05T07:01:00Z", mails_count: 3, error: null, step: null, total: 0 }, next_full_at: "2026-11-05T12:00:00Z", next_light_at: null },
    "GET /api/boxes/summary": boxes,
    "GET /api/oauth/providers": { google: false, microsoft: false },
    "GET /api/folders": folders,
    "GET /api/messages": { items: inboxMessages, next_before_id: null },
  };
  const all = { ...defaults, ...handlers };
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    const call: Call = { method, path: url.pathname, query: url.searchParams, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const h = all[`${method} ${url.pathname}`];
    if (h === undefined) throw new Error(`fetch non simulé : ${method} ${url.pathname}`);
    return typeof h === "function" ? (h as Handler)(call) : jsonResponse(h);
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

export function setViewportWide(wide: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: wide, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }));
}
