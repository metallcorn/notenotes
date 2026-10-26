import { AlarmClock, CalendarDays, ChevronRight, Pill } from "lucide-react";
import { useAllNotifications, useDetectedEvents } from "../api/hooks";
import { dateLocale, t } from "../i18n";

// «Скоро» на Главной телефона (замечание 22.10: «главная — не просто
// последние заметки, а сводка: ближайшие события кратко»). Те же данные,
// что у «Активности»: ещё не наступившие напоминания и найденные в
// заметках события, ближайшие четыре. Тап — открыть заметку, «Вся
// активность» — на вкладку.
type Entry = { key: string; at: Date; title: string; sub: string; kind: "reminder" | "event" | "dose"; spaceId?: string; itemId?: string; entryId?: string; notificationId?: string };

export default function UpcomingCard({
  onOpen,
  onOpenItem,
  onAll,
}: {
  onOpen: (spaceId: string, itemId: string, entryId?: string, notificationId?: string) => void;
  onOpenItem: (spaceId: string, itemId: string) => void;
  onAll: () => void;
}) {
  const { data: notifications } = useAllNotifications();
  const { data: events } = useDetectedEvents();
  const now = Date.now();
  const horizon = now + 14 * 86_400_000;
  const entries: Entry[] = [
    ...(notifications ?? [])
      .filter((n) => !n.resolved_at && n.trigger_at && new Date(n.trigger_at).getTime() > now)
      .map((n): Entry => ({
        key: `n-${n.id}`,
        at: new Date(n.trigger_at!),
        title: n.title,
        sub: n.type === "routine_dose" ? `${t("routine.doseShort")}${n.body ? ` · ${n.body}` : ""}` : "напоминание",
        kind: n.type === "routine_dose" ? "dose" : "reminder",
        spaceId: n.payload.space_id as string | undefined,
        itemId: n.payload.item_id as string | undefined,
        entryId: n.payload.entry_id as string | undefined,
        notificationId: n.id,
      })),
    ...(events ?? [])
      .filter((e) => new Date(e.event_at).getTime() > now)
      .map((e): Entry => ({
        key: `e-${e.item_id}-${e.event_at}`,
        at: new Date(e.event_at),
        title: e.event_title,
        sub: e.item_title,
        kind: "event",
        spaceId: e.space_id,
        itemId: e.item_id,
      })),
  ]
    .filter((e) => e.at.getTime() <= horizon)
    .sort((a, b) => a.at.getTime() - b.at.getTime())
    .slice(0, 4);

  if (entries.length === 0) return null;

  const when = (d: Date) => {
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    const time = d.toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" });
    if (sameDay) return `сегодня, ${time}`;
    if (d.toDateString() === tomorrow.toDateString()) return `завтра, ${time}`;
    return d.toLocaleDateString(dateLocale, { weekday: "short", day: "numeric", month: "short" }) + `, ${time}`;
  };

  return (
    <section aria-label={t("home.upcoming")} className="mb-3">
      <div className="mb-2 flex items-baseline justify-between px-1">
        <h2 className="text-lg font-extrabold tracking-tight text-primary">{t("home.upcoming")}</h2>
        <button onClick={onAll} className="text-sm font-bold text-brand-text">
          {t("home.allUpcoming")}
        </button>
      </div>
      <ul className="rounded-2xl bg-surface p-1.5 shadow-card">
        {entries.map((e) => (
          <li key={e.key}>
            <button
              onClick={() => {
                if (!e.spaceId || !e.itemId) {
                  onAll();
                  return;
                }
                if (e.kind === "reminder") onOpen(e.spaceId, e.itemId, e.entryId, e.notificationId);
                else onOpenItem(e.spaceId, e.itemId);
              }}
              className="flex min-h-[52px] w-full items-center gap-3 rounded-xl px-2 text-left hover:bg-muted"
            >
              <span
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
                  e.kind === "event" ? "bg-lime/60 text-on-lime" : "bg-brand-soft text-brand-text"
                }`}
              >
                {e.kind === "reminder" ? <AlarmClock size={16} strokeWidth={2.2} /> : e.kind === "dose" ? <Pill size={16} strokeWidth={2.2} /> : <CalendarDays size={16} strokeWidth={2.2} />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[15px] font-extrabold text-primary">{e.title}</span>
                <span className="block truncate text-xs font-semibold text-subtle">
                  {when(e.at)} · {e.sub}
                </span>
              </span>
              <ChevronRight size={16} className="shrink-0 text-subtle" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
