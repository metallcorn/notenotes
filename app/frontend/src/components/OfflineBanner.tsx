import { CloudOff } from "lucide-react";
import { useOnline } from "../lib/useOnline";

/**
 * Полоска «нет сети». Нужна не для красоты: офлайн приложение показывает
 * последние СОХРАНЁННЫЕ данные, и без предупреждения человек не отличит
 * их от свежих — а правки в это время никуда не уйдут.
 *
 * Жалоба 02.10 была обратной («офлайн не видно ничего»), но, починив
 * видимость, надо сразу сказать и о её цене.
 */
export default function OfflineBanner() {
  if (useOnline()) return null;

  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 bg-warning/15 px-3 py-1 text-xs text-warning"
    >
      <CloudOff size={13} aria-hidden />
      Нет сети — показано сохранённое. Правки сохранятся, когда связь вернётся.
    </div>
  );
}
