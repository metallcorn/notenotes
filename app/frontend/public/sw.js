// Минимальный service worker для установки PWA — намеренно не кэширует
// ничего, кроме иммутабельных ассетов из /assets/ (имя файла = хэш
// содержимого от Vite, так что кэшировать их навсегда безопасно). Всё
// остальное (index.html, /api/*) — только сеть, без исключений.
//
// index.html отдаётся бэкендом с Cache-Control: no-store специально для
// того, чтобы устаревший бандл не залипал в браузере (main.py, useVersionCheck)
// — service worker с кэшем index.html свёл бы этот фикс на нет, поэтому его
// здесь нет и не должно появиться.

const ASSET_CACHE = "notenotes-assets-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== ASSET_CACHE).map((key) => caches.delete(key))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/assets/")) return;

  event.respondWith(
    caches.open(ASSET_CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok) cache.put(request, response.clone());
      return response;
    }),
  );
});
