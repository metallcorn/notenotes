import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

// Live-синк заметок/папок/диалогов между устройствами и участниками спейса
// (жалоба: правки с телефона не появлялись на ноутбуке без ручной
// перезагрузки страницы). В отличие от useListSync сервер не шлёт данные
// целиком — только лёгкий сигнал "kind изменился" (items/folders/dialogs),
// клиент сам решает, что перезапросить через react-query.
export function useSpaceSync(spaceId: string | undefined) {
  const qc = useQueryClient();

  useEffect(() => {
    if (!spaceId) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/spaces/${spaceId}/ws`);
    ws.onmessage = (event) => {
      try {
        const data: { kind?: string } = JSON.parse(event.data);
        if (data.kind === "items") {
          qc.invalidateQueries({ queryKey: ["items"] });
          // "items" (список) и "item" (одна открытая заметка) — разные
          // ключи ("item" не является префиксом "items"), invalidateQueries
          // не задевал бы открытую заметку сам. Без этого фоновая
          // обработка файла (OCR PDF/расшифровка), законченная, пока
          // заметка открыта, никогда не подтягивалась в уже смонтированный
          // редактор — реально пойманный баг: карточка так и оставалась
          // плейсхолдером "обрабатывается…" навсегда, а следующий автосейв
          // тем же самым устаревшим текстом затирал готовый результат
          // обратно на сервере.
          qc.invalidateQueries({ queryKey: ["item"] });
        } else if (data.kind === "folders") {
          qc.invalidateQueries({ queryKey: ["folders"] });
        } else if (data.kind === "dialogs") {
          qc.invalidateQueries({ queryKey: ["dialog"] });
          qc.invalidateQueries({ queryKey: ["dialogs"] });
        }
      } catch {
        // нераспознанное сообщение — игнорируем
      }
    };
    return () => ws.close();
  }, [spaceId, qc]);
}
