/// <reference lib="webworker" />
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
  const url = new URL((event.notification.data as { url?: string })?.url ?? "/", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const w of wins) {
        if ("focus" in w) {
          await w.focus();
          if ("navigate" in w) await w.navigate(url);
          return;
        }
      }
      await self.clients.openWindow(url);
    })(),
  );
});
