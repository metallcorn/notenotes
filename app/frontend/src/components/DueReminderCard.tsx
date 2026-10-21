import { Check } from "lucide-react";
import { useNotifications, useResolveNotification, useSnoozeNotification } from "../api/hooks";
import type { Notification } from "../api/types";
import Spinner from "./Spinner";
import { dateLocale, t } from "../i18n";

// Карточка «Висит · N» на «Главной» (редизайн 21.10): первое наступившее и
// не закрытое напоминание с кнопками «Сделано» и «Завтра» — те же мутации,
// что у строки в «Активности», просто на виду, а не за колокольчиком.
// Данные — useNotifications (только наступившие, scope=due): это же
// список колокольчика, отдельного запроса не нужно.
export function dueReminders(notifications: Notification[] | undefined): Notification[] {
  const now = Date.now();
  return (notifications ?? [])
    .filter((n) => !n.resolved_at && n.trigger_at && new Date(n.trigger_at).getTime() <= now)
    .sort((a, b) => new Date(a.trigger_at!).getTime() - new Date(b.trigger_at!).getTime());
}

export default function DueReminderCard({
  onOpen,
  onMore,
}: {
  onOpen: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
  onMore: () => void;
}) {
  const { data: notifications } = useNotifications();
  const resolve = useResolveNotification();
  const snooze = useSnoozeNotification();
  const due = dueReminders(notifications);
  if (due.length === 0) return null;
  const first = due[0];
  const spaceId = first.payload.space_id as string | undefined;
  const itemId = first.payload.item_id as string | undefined;
  const since = new Date(first.trigger_at!).toLocaleDateString(dateLocale, { day: "numeric", month: "long" });
  const busy = resolve.isPending || snooze.isPending;

  return (
    <section aria-label={t("home.due")} className="row-fade-in mb-3 rounded-3xl bg-lime p-4 text-on-lime">
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-extrabold uppercase tracking-wider">
          {t("home.due")} · {due.length}
        </div>
        <div className="text-[13px] font-semibold opacity-70">с {since}</div>
      </div>
      <button
        type="button"
        onClick={() => spaceId && itemId && onOpen(spaceId, itemId, first.payload.entry_id as string | undefined, first.id, first.payload.find as string | undefined)}
        disabled={!spaceId || !itemId}
        className="mt-1.5 block w-full truncate text-left text-[19px] font-extrabold leading-tight tracking-tight disabled:cursor-default"
      >
        {first.title}
      </button>
      {first.body && <div className="mt-0.5 truncate text-sm font-medium opacity-70">{first.body}</div>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => resolve.mutate(first.id)}
          disabled={busy}
          className="flex h-10 items-center gap-1.5 rounded-full bg-nav px-4 text-sm font-bold text-nav-text disabled:opacity-60"
        >
          {resolve.isPending ? <Spinner size={14} /> : <Check size={16} strokeWidth={2.6} />}
          {t("home.done")}
        </button>
        <button
          type="button"
          onClick={() => snooze.mutate({ id: first.id, preset: "tomorrow" })}
          disabled={busy}
          className="h-10 rounded-full border-[1.5px] border-on-lime px-4 text-sm font-bold disabled:opacity-60"
        >
          {t("home.tomorrow")}
        </button>
        {due.length > 1 && (
          <button
            type="button"
            onClick={onMore}
            className="h-10 rounded-full bg-on-lime/10 px-3.5 text-sm font-bold"
          >
            {t("home.more", { n: due.length - 1 })}
          </button>
        )}
      </div>
    </section>
  );
}
