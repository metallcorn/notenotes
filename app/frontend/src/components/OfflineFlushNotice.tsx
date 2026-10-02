import { Check, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { useOfflineFlush } from "../lib/useOfflineFlush";

/**
 * Что стало с правками, сделанными без сети.
 *
 * Молча отправить — плохо в обе стороны: человек не знает, дошло ли, и
 * тем более не знает про конфликт. А конфликт здесь не ошибка, а
 * сознательное решение (см. offlineQueue.ts): вместо затирания мы
 * сохранили копию, и об этом обязаны сказать — иначе копия станет
 * сюрпризом, а человек будет уверен, что правка применилась.
 */
export default function OfflineFlushNotice() {
  const outcomes = useOfflineFlush();
  const [dismissed, setDismissed] = useState(false);

  if (!outcomes.length || dismissed) return null;

  const saved = outcomes.filter((o) => o.status === "saved").length;
  const conflicts = outcomes.filter((o) => o.status === "conflict");
  const failed = outcomes.filter((o) => o.status === "failed").length;

  return (
    <div role="status" className="flex items-start gap-2 bg-muted-hover px-3 py-1.5 text-xs text-secondary">
      {conflicts.length ? <TriangleAlert size={13} className="mt-0.5 shrink-0 text-warning" aria-hidden />
        : <Check size={13} className="mt-0.5 shrink-0 text-accent" aria-hidden />}
      <div className="min-w-0 flex-1">
        {saved > 0 && <div>Отправлено правок, сделанных без сети: {saved}.</div>}
        {conflicts.map((c) => (
          <div key={c.itemId}>
            Заметку «{"copyTitle" in c ? c.copyTitle.replace(" (офлайн-правка)", "") : ""}» успели изменить
            с другого устройства — ваша версия сохранена рядом, отдельной заметкой, чтобы ничего не затереть.
          </div>
        ))}
        {failed > 0 && <div>Не удалось отправить: {failed}. Попробуем ещё раз при следующем подключении.</div>}
      </div>
      <button onClick={() => setDismissed(true)} aria-label="Скрыть" className="shrink-0 text-subtle hover:text-primary">
        <X size={13} />
      </button>
    </div>
  );
}
