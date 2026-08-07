import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ListDetail } from "../api/types";

// Реалтайм-синк списка (ТЗ §12): сервер шлёт полный ListOut при каждом
// изменении пункта — своим или чужим. REST-мутации уже кладут ответ в кеш
// сами (см. useAddListEntry и т.д.), это только для изменений ОТ ДРУГИХ
// клиентов/ассистента.
export function useListSync(listId: string | undefined) {
  const qc = useQueryClient();

  useEffect(() => {
    if (!listId) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/lists/${listId}/ws`);
    ws.onmessage = (event) => {
      try {
        const data: ListDetail = JSON.parse(event.data);
        qc.setQueryData(["list", listId], data);
      } catch {
        // нераспознанное сообщение — игнорируем
      }
    };
    return () => ws.close();
  }, [listId, qc]);
}
