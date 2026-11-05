import { apiGet, apiSend } from "./api";
import type { PushSubscribeBody, VapidKey } from "./types";

export const INSTALL_MESSAGE = "Installe d'abord l'appli : Partager › Sur l'écran d'accueil";

export type PushResult =
  | { ok: true }
  | { ok: false; reason: "not-installed" | "unsupported" | "denied" | "error"; message: string };

export function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

const isStandalone = () =>
  Boolean(window.matchMedia?.("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone);

const isIos = () =>
  /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

/** Abonne cet appareil au Web Push. iOS exige l'appli installée ; les navigateurs desktop l'acceptent sans. */
export async function subscribeToPush(): Promise<PushResult> {
  if (isIos() && !isStandalone()) return { ok: false, reason: "not-installed", message: INSTALL_MESSAGE };
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || typeof Notification === "undefined") {
    return { ok: false, reason: "unsupported", message: "Les notifications ne sont pas disponibles sur ce navigateur." };
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      return { ok: false, reason: "denied", message: "Notifications refusées dans les réglages du navigateur" };
    }
    const { key } = await apiGet<VapidKey>("/api/push/vapid-public-key");
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
    const json = subscription.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
    const body: PushSubscribeBody = { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } };
    await apiSend("POST", "/api/push/subscribe", body);
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: "error", message: e instanceof Error && e.message ? e.message : "Impossible d'activer les notifications" };
  }
}
