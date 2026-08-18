import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { TableDetail } from "../api/types";

// Реалтайм-синк таблицы — та же схема, что у списков (lib/useListSync.ts):
// сервер шлёт полный TableOut при каждом изменении строки/столбца, своим
// или чужим. REST-мутации уже кладут ответ в кеш сами, это только для
// изменений ОТ ДРУГИХ клиентов/ассистента.
export function useTableSync(tableId: string | undefined) {
  const qc = useQueryClient();

  useEffect(() => {
    if (!tableId) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/tables/${tableId}/ws`);
    ws.onmessage = (event) => {
      try {
        const data: TableDetail = JSON.parse(event.data);
        qc.setQueryData(["table", tableId], data);
      } catch {
        // нераспознанное сообщение — игнорируем
      }
    };
    return () => ws.close();
  }, [tableId, qc]);
}
