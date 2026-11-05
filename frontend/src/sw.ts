/// <reference lib="webworker" />
import { resolveNotificationUrl } from "./notificationUrl";
import { precacheAndRoute, cleanupOutdatedCaches } from "workbox-precaching";

declare const self: ServiceWorkerGlobalScope;

cleanupOutdatedCaches();
precacheAndRoute(self.__WB_MANIFEST);

self.addEventListener("install", () => void self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

interface PushPayload { title?: string; body?: string; data?: { url?: string } }

self.addEventListener("push", (event) => {
  let p: PushPayload = {};
  try {
    p = event.data ? (event.data.json() as PushPayload) : {};
  } catch {
    p = { body: event.data?.text() };
  }
  event.waitUntil(
    self.registration.showNotification(p.title ?? "Mail Pilot", {
      body: p.body ?? "",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: p.data?.url ?? "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = resolveNotificationUrl((event.notification.data as { url?: string } | null)?.url, self.location.origin);
  event.waitUntil(
    (async () => {
      const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const w of wins) {
        try {
          await w.focus();
          await w.navigate(target);
          return;
        } catch {
          // client non contrôlable : on essaie le suivant, puis on ouvre une fenêtre
        }
      }
      await self.clients.openWindow(target);
    })(),
  );
});
