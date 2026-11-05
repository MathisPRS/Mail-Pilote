/** URL cible d'un clic de notification : même origine uniquement, sinon l'accueil. */
export function resolveNotificationUrl(raw: unknown, origin: string): string {
  try {
    const u = new URL(typeof raw === "string" && raw ? raw : "/", origin);
    return u.origin === origin ? u.href : `${origin}/`;
  } catch {
    return `${origin}/`;
  }
}
