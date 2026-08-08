// Персист react-query кэша в IndexedDB (ТЗ §18 — offline read-only) —
// localStorage слишком мал и синхронен для растущего кэша заметок/файлов
// на много сотен КБ, IndexedDB подходит по размеру и есть промисный API
// через idb-keyval. Формат хранения — деталь именно этого персистера, не
// общий контракт с sw.js (в отличие от offlineSettings.ts), поэтому здесь
// без ограничений на внутреннее устройство idb-keyval.
import { get, set, del } from "idb-keyval";
import type { Persister } from "@tanstack/react-query-persist-client";

const CACHE_KEY = "notenotes-query-cache";

export const idbPersister: Persister = {
  persistClient: async (client) => {
    await set(CACHE_KEY, client);
  },
  restoreClient: async () => {
    return await get(CACHE_KEY);
  },
  removeClient: async () => {
    await del(CACHE_KEY);
  },
};
