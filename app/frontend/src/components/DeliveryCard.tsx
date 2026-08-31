import type { ReactNode } from "react";
import { ExternalLink, Package } from "lucide-react";

// Карточка статуса доставки в чате ассистента. Рисуется из результата тула
// track_delivery (app/backend/app/delivery.py) — данные уже нормализованы,
// здесь только отображение. Несколько посылок в одном ответе показываются
// стопкой (см. DeliveryResultCards в AssistantChat.tsx).

export interface DeliveryData {
  carrier?: string;
  carrier_label?: string;
  tracking_number?: string;
  live?: boolean;
  status_text?: string;
  last_event_time?: string;
  checkpoints?: { time?: string; status?: string; description?: string }[];
  tracking_url?: string;
  note?: string;
  need_carrier?: boolean;
  supported?: { id: string; label: string }[];
  message?: string;
}

function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function DeliveryCard({ data, headerExtra }: { data: DeliveryData; headerExtra?: ReactNode }) {
  // Перевозчик не определился — тул просит уточнить. Показываем это явно,
  // чтобы пользователь понял, почему статуса нет.
  if (data.need_carrier) {
    return (
      <div className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
        <div className="flex items-start justify-between gap-2">
          <div>
            {data.message || "Не удалось определить перевозчика по номеру."}
            {data.supported && data.supported.length > 0 && (
              <div className="mt-1 text-warning">
                Поддерживаются: {data.supported.map((s) => s.label).join(", ")}
              </div>
            )}
          </div>
          {headerExtra}
        </div>
      </div>
    );
  }

  const checkpoints = data.checkpoints ?? [];
  const lastTime = fmtTime(data.last_event_time || checkpoints[0]?.time);

  return (
    <div className="rounded-lg border border-default bg-surface px-3 py-2.5 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 font-medium text-primary">
          <Package size={14} className="text-subtle" />
          {data.carrier_label || data.carrier || "Доставка"}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {data.tracking_url && (
            <a
              href={data.tracking_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-0.5 text-xs text-subtle hover:text-secondary"
            >
              Трекинг <ExternalLink size={11} />
            </a>
          )}
          {headerExtra}
        </div>
      </div>

      <div className="mt-1 font-semibold text-primary">
        {data.status_text || (data.live ? "—" : "Статус доступен по ссылке")}
      </div>

      {(lastTime || data.note) && (
        <div className="mt-0.5 text-xs text-subtle">
          {[lastTime, data.note].filter(Boolean).join(" · ")}
        </div>
      )}

      {data.tracking_number && (
        <div className="mt-1 font-mono text-[11px] text-subtle">{data.tracking_number}</div>
      )}

      {checkpoints.length > 1 && (
        <ol className="mt-2 space-y-1 border-t border-default pt-2">
          {checkpoints.slice(0, 5).map((c, i) => (
            <li key={i} className="flex gap-2 text-xs text-secondary">
              <span className="shrink-0 text-subtle">{fmtTime(c.time)}</span>
              <span>{c.description || c.status}</span>
            </li>
          ))}
        </ol>
      )}

      {!data.live && (
        <div className="mt-1 text-[11px] text-subtle">Живой статус недоступен — открой трекинг по ссылке.</div>
      )}
    </div>
  );
}
