/** Contenu d'une notification Web Push : {title, body, data: {url}} (ou `url` à la racine). */
export interface ParsedPush {
  title: string;
  body: string;
  url: string;
}

const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

export function parsePushPayload(raw: string | null | undefined): ParsedPush {
  let p: Record<string, unknown> = {};
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      p = parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : { body: raw };
    } catch {
      p = { body: raw };
    }
  }
  const data = p.data && typeof p.data === "object" ? (p.data as Record<string, unknown>) : {};
  return {
    title: str(p.title) ?? "Mail Pilot",
    body: str(p.body) ?? "",
    url: str(data.url) ?? str(p.url) ?? "/",
  };
}
