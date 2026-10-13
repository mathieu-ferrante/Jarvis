// Service worker minimal : met l'interface en cache (ouverture hors connexion, TEL-07 en secours)
// et affiche les notifications. Aucun service de push tiers : les notifications arrivent par la
// connexion WebSocket directe avec le PC (via Tailscale).
const CACHE = "jarvis-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icone.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((cles) => Promise.all(cles.filter((c) => c !== CACHE).map((c) => caches.delete(c)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/ws") || e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copie = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copie));
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/"))),
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window" }).then((fenetres) => (fenetres[0] ? fenetres[0].focus() : self.clients.openWindow("/"))));
});
