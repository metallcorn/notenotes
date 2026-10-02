import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { flushQueue, readQueue, type FlushOutcome } from "./offlineQueue";
import type { Item } from "../api/types";

/**
 * Отправляет накопленные офлайн-правки, когда связь возвращается.
 *
 * Живёт в оболочке приложения, а не в редакторе: правки могли быть
 * сделаны в заметке, которая сейчас даже не открыта (или вкладку
 * закрывали и открывали заново), и ждать, пока человек туда вернётся,
 * нельзя.
 */
export function useOfflineFlush(): FlushOutcome[] {
  const qc = useQueryClient();
  const [outcomes, setOutcomes] = useState<FlushOutcome[]>([]);
  const running = useRef(false);

  useEffect(() => {
    async function flush() {
      // Один проход за раз: событие «online» прилетает пачкой, и без
      // этого две отправки гонялись бы за одну и ту же правку.
      if (running.current || !navigator.onLine) return;
      if ((await readQueue()).length === 0) return;
      running.current = true;
      try {
        const results = await flushQueue({
          fetchItem: async (id) => {
            try {
              const item = await api.get<Item>(`/items/${id}`);
              return { updated_at: item.updated_at, title: item.title, space_id: item.space_id };
            } catch {
              // 404 — заметку удалили, пока мы были офлайн. Отличить её от
              // сетевой ошибки нельзя, и это к лучшему: оба случая ведут
              // к копии, то есть текст в любом случае цел.
              return null;
            }
          },
          patchItem: async (edit) => {
            await api.patch<Item>(`/items/${edit.itemId}`, { title: edit.title, content: edit.content });
          },
          createCopy: async (edit, title, spaceId) => {
            const space = spaceId || (await api.get<Item>(`/items/${edit.itemId}`).catch(() => null))?.space_id;
            if (!space) throw new Error("некуда сохранить копию");
            await api.post<Item>("/items", { space_id: space, title, content: edit.content });
          },
        });
        if (results.length) {
          setOutcomes(results);
          // Свежие данные с сервера: мы только что их изменили.
          qc.invalidateQueries({ queryKey: ["items"] });
        }
      } finally {
        running.current = false;
      }
    }

    void flush();
    window.addEventListener("online", flush);
    return () => window.removeEventListener("online", flush);
  }, [qc]);

  return outcomes;
}
