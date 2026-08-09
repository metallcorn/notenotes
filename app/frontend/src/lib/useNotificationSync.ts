import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

// Тот же паттерн, что useSpaceSync.ts, но привязан к пользователю, не к
// спейсу (уведомления не спейс-скоуп) — держит соединение с
// /api/notifications/ws, на входящий сигнал перезапрашивает список вместо
// ожидания опроса (см. useNotifications). Не принимает spaceId/userId —
// сервер сам знает пользователя по сессионной куке, соединение нужно
// держать всегда, пока пользователь залогинен, а не только на части экранов.
export function useNotificationSync() {
  const qc = useQueryClient();

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/notifications/ws`);
    ws.onmessage = (event) => {
      try {
        const data: { kind?: string } = JSON.parse(event.data);
        if (data.kind === "notifications") {
          qc.invalidateQueries({ queryKey: ["notifications"] });
        }
      } catch {
        // нераспознанное сообщение — игнорируем
      }
    };
    return () => ws.close();
  }, [qc]);
}
