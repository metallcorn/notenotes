// Настройка лимита кэша медиа для офлайн-режима (ТЗ §18) — намеренно на
// IndexedDB, а не localStorage (как остальной lib/storage.ts): читать её
// должен и service worker (public/sw.js), у которого нет доступа к
// localStorage/React state, а IndexedDB доступна из обеих сред. Схема
// (база/store/ключ) — общий контракт с sw.js, при изменении держать оба
// файла в синхронизации.

const DB_NAME = "notenotes-settings";
const STORE_NAME = "kv";
const LIMIT_KEY = "mediaCacheLimitBytes";

export const DEFAULT_MEDIA_CACHE_LIMIT_MB = 5;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE_NAME)) {
        req.result.createObjectStore(STORE_NAME);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet<T>(key: string): Promise<T | undefined> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).get(key);
    req.onsuccess = () => resolve(req.result as T | undefined);
    req.onerror = () => reject(req.error);
  });
}

async function idbSet(key: string, value: unknown): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function getMediaCacheLimitBytes(): Promise<number> {
  const value = await idbGet<number>(LIMIT_KEY);
  return typeof value === "number" && value > 0 ? value : DEFAULT_MEDIA_CACHE_LIMIT_MB * 1024 * 1024;
}

export async function setMediaCacheLimitMb(mb: number): Promise<void> {
  await idbSet(LIMIT_KEY, Math.max(0, mb) * 1024 * 1024);
}
