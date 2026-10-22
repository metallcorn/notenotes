import { useEffect, useState } from "react";
import { useMe, useUpdateDigestTime } from "../api/hooks";

/**
 * Утренняя сводка «что сегодня» — в Telegram с кнопками и в push.
 *
 * Одно поле, а не тумблер + время: «включено, но без времени» состояния
 * не имеет. Выключено = время пустое.
 */
export default function DigestSettings() {
  const { data: me } = useMe();
  const update = useUpdateDigestTime();
  const enabled = Boolean(me?.digest_time);
  const [time, setTime] = useState(me?.digest_time ?? "09:00");

  useEffect(() => {
    if (me?.digest_time) setTime(me.digest_time);
  }, [me?.digest_time]);

  return (
    <div className="mb-6">
      <div className="mb-1 text-sm font-medium text-primary">Утренняя сводка</div>
      <div className="mb-2 text-xs text-subtle">
        Что на сегодня: напоминания и события, которые нашлись в письмах, билетах и заметках. Приходит в
        Telegram с кнопками «сделано» и «не актуально» — и в уведомления, если Telegram не подключён.
        Если на день ничего нет, не приходит.
      </div>
      <div className="flex items-center gap-3">
        <button
          role="switch"
          aria-checked={enabled}
          aria-label="Утренняя сводка"
          onClick={() => update.mutate(enabled ? "" : time || "09:00")}
          disabled={update.isPending}
          className={`flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors disabled:opacity-50 ${
            enabled ? "justify-end bg-accent" : "justify-start bg-muted-active"
          }`}
        >
          <span className="h-4 w-4 rounded-full bg-surface shadow" />
        </button>
        <label className="flex items-center gap-2 text-sm text-secondary">
          в
          <input
            type="time"
            value={time}
            disabled={!enabled || update.isPending}
            onChange={(e) => setTime(e.target.value)}
            onBlur={() => {
              if (enabled && time && time !== me?.digest_time) update.mutate(time);
            }}
            className="h-10 rounded-xl border bg-surface px-3 text-sm outline-none focus:ring-2 focus:ring-brand/40 disabled:opacity-50"
          />
          <span className="text-xs text-subtle">по вашему часовому поясу</span>
        </label>
      </div>
    </div>
  );
}
