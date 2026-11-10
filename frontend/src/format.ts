import type { Category, FolderRole } from "./types";

const TZ = "Europe/Paris";

/** Le backend renvoie de l'ISO 8601 ; sans fuseau on suppose UTC. */
export function parseDate(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
}

const valid = (iso: string | null | undefined): iso is string => !!iso && !Number.isNaN(parseDate(iso).getTime());

export function formatClock(iso: string | null | undefined): string {
  if (!valid(iso)) return "";
  return parseDate(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: TZ });
}

const dayKey = (d: Date) => d.toLocaleDateString("fr-CA", { timeZone: TZ });

/** Date d'une ligne : heure aujourd'hui, « Hier », jour de semaine (< 7 j), sinon jj/mm. */
export function formatRowDate(iso: string | null | undefined, now: Date = new Date()): string {
  if (!valid(iso)) return "";
  const d = parseDate(iso);
  const days = Math.round((Date.parse(dayKey(now)) - Date.parse(dayKey(d))) / 86_400_000);
  if (days <= 0) return formatClock(iso);
  if (days === 1) return "Hier";
  if (days < 7) {
    const w = d.toLocaleDateString("fr-FR", { weekday: "short", timeZone: TZ });
    return w.charAt(0).toUpperCase() + w.slice(1);
  }
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", timeZone: TZ });
}

export function formatFull(iso: string | null | undefined): string {
  if (!valid(iso)) return "";
  return parseDate(iso).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short", timeZone: TZ });
}

export const CATEGORY_TAGS: Partial<Record<Category, string>> = {
  important: "Important", action: "À traiter", tt: "TT+", news: "Newsletter", pub: "Pub", spam: "Spam",
};

export const CHIPS: [Category | "all", string][] = [
  ["all", "Tout"], ["important", "Important"], ["action", "À traiter"], ["tt", "TT+"],
  ["info", "Infos"], ["news", "Newsletters"], ["pub", "Pub"], ["spam", "Spam"],
];

export const PRIORITY_DOT: Partial<Record<Category, string>> = { tt: "#0F5C4D", important: "#C2410C", action: "#1F6FEB" };

export const ROLE_LABELS: Record<FolderRole, string> = {
  inbox: "Réception", drafts: "Brouillons", sent: "Envoyés", junk: "Indésirables", archive: "Archives", trash: "Corbeille",
};

export const isPriorityCategory = (c: Category | null) => c === "tt" || c === "important" || c === "action";

export const plural = (n: number, one: string, many: string) => `${n} ${n > 1 ? many : one}`;

/** « 08:12 » aujourd'hui, « hier 22:10 », « lundi 08:12 » (< 7 j), sinon « 05/11 08:12 » : pour « depuis … ». */
export function formatSince(iso: string | null | undefined, now: Date = new Date()): string {
  if (!valid(iso)) return "";
  const d = parseDate(iso);
  const days = Math.round((Date.parse(dayKey(now)) - Date.parse(dayKey(d))) / 86_400_000);
  const clock = formatClock(iso);
  if (days <= 0) return clock;
  if (days === 1) return `hier ${clock}`;
  if (days < 7) return `${d.toLocaleDateString("fr-FR", { weekday: "long", timeZone: TZ })} ${clock}`;
  return `${d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", timeZone: TZ })} ${clock}`;
}
