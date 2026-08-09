// Service worker для PWA (ТЗ §18 — offline read-only). Три обработчика по
// типу запроса:
//
// - навигация (сам HTML-каркас) — network-first с офлайн-фолбэком на
//   закэшированную версию. index.html отдаётся бэкендом с Cache-Control:
//   no-store специально для того, чтобы устаревший бандл не залипал в
//   БРАУЗЕРНОМ HTTP-кэше (main.py, useVersionCheck) — Cache Storage этот
//   заголовок не учитывает вовсе, так что ручное кэширование здесь ему не
//   противоречит: онлайн всегда берётся свежая сеть (тот же эффект, что
//   и раньше), кэш — только фолбэк, когда сети реально нет.
// - /assets/* — как и раньше, cache-first (иммутабельно, хэш в имени от Vite).
// - /api/uploads/* — cache-first с сетевым фолбэком; кэшируется только если
//   Content-Length не больше лимита из настроек (offlineSettings.ts на
//   стороне React, здесь — сырая копия той же read-функции: SW не обрабатывается
//   Vite'ом, TS-модуль сюда не заимпортить).
//
// Данные (заметки/списки/теги) сюда не входят — это зона react-query
// персиста в IndexedDB (main.tsx), не service worker'а.

const SHELL_CACHE = "notenotes-shell-v1";
const ASSET_CACHE = "notenotes-assets-v1";
const MEDIA_CACHE = "notenotes-media-v1";
const CURRENT_CACHES = [SHELL_CACHE, ASSET_CACHE, MEDIA_CACHE];
const SHELL_KEY = "/";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => !CURRENT_CACHES.includes(key)).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

// --- offlineSettings.ts, сырая копия read-стороны для SW (см. комментарий там) ---
const SETTINGS_DB_NAME = "notenotes-settings";
const SETTINGS_STORE_NAME = "kv";
const MEDIA_LIMIT_KEY = "mediaCacheLimitBytes";
const DEFAULT_MEDIA_LIMIT_BYTES = 5 * 1024 * 1024;

function getMediaCacheLimitBytes() {
  return new Promise((resolve) => {
    const openReq = indexedDB.open(SETTINGS_DB_NAME, 1);
    openReq.onupgradeneeded = () => {
      if (!openReq.result.objectStoreNames.contains(SETTINGS_STORE_NAME)) {
        openReq.result.createObjectStore(SETTINGS_STORE_NAME);
      }
    };
    openReq.onerror = () => resolve(DEFAULT_MEDIA_LIMIT_BYTES);
    openReq.onsuccess = () => {
      const db = openReq.result;
      try {
        const tx = db.transaction(SETTINGS_STORE_NAME, "readonly");
        const getReq = tx.objectStore(SETTINGS_STORE_NAME).get(MEDIA_LIMIT_KEY);
        getReq.onsuccess = () => {
          const value = getReq.result;
          resolve(typeof value === "number" && value > 0 ? value : DEFAULT_MEDIA_LIMIT_BYTES);
        };
        getReq.onerror = () => resolve(DEFAULT_MEDIA_LIMIT_BYTES);
      } catch {
        resolve(DEFAULT_MEDIA_LIMIT_BYTES);
      }
    };
  });
}

// На плохой мобильной сети fetch() может не упасть, а просто ЗАВИСНУТЬ —
// тогда catch с фолбэком на закэшированный каркас ниже никогда не
// срабатывал, и пользователь смотрел на чёрный экран сколько угодно
// (реальная жалоба: "приложение либо очень долго грузится, либо вообще
// перестаёт грузиться"). AbortController с таймаутом превращает зависание
// в обычную сетевую ошибку, которую catch уже умеет обрабатывать.
const NAVIGATE_TIMEOUT_MS = 4000;

async function handleNavigate(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), NAVIGATE_TIMEOUT_MS);
    try {
      const response = await fetch(request, { signal: controller.signal });
      if (response.ok) cache.put(SHELL_KEY, response.clone());
      return response;
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    const cached = await cache.match(SHELL_KEY);
    if (cached) return cached;
    throw new Error("offline и нет закэшированного каркаса");
  }
}

async function handleAsset(request) {
  const cache = await caches.open(ASSET_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

async function handleUpload(request) {
  const cache = await caches.open(MEDIA_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const len = Number(response.headers.get("content-length") || "0");
    const limit = await getMediaCacheLimitBytes();
    if (len > 0 && len <= limit) {
      cache.put(request, response.clone());
    }
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  if (request.mode === "navigate") {
    event.respondWith(handleNavigate(request));
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(handleAsset(request));
  } else if (url.pathname.startsWith("/api/uploads/")) {
    event.respondWith(handleUpload(request));
  }
});
