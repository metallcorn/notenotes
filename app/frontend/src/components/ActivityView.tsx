import { useMemo, useState } from "react";
import {
  AlarmClock,
  Bell,
  BellOff,
  Calendar,
  CalendarClock,
  Check,
  ChevronLeft,
  ListChecks,
  MessageSquare,
  Repeat,
  Sparkles,
  StickyNote,
  X,
  Pill,
} from "lucide-react";
import {
  useAllNotifications,
  useDeleteNotification,
  useDetectedEvents,
  useDialogs,
  useDismissDetectedEvent,
  useMarkNotificationRead,
  useRecentItems,
  useResolveNotification,
  useSnoozeNotification,
  useSpaces,
  useUnresolveNotification,
} from "../api/hooks";
import type { SnoozePreset } from "../api/hooks";
import { useMe, useRoutineDoseAction } from "../api/hooks";
import { humanMinutes } from "../lib/routineFormat";
import type { DetectedEvent, Notification } from "../api/types";
import { repeatLabel } from "../lib/recurrence";
import { ListSkeleton } from "./Skeleton";
import SwipeRow from "./SwipeRow";
import { dateLocale, t } from "../i18n";

type Tab = "notifications" | "recent";

// Реальная жалоба: события с датой (билеты/напоминания) сегодня терялись
// среди остальных активных — список сортирован по trigger_at, но найти
// "что у меня сегодня" всё равно приходилось визуальным сканированием.
// Первая версия делала это переключателем-фильтром (клик, чтобы увидеть) —
// отклонено: "также как активные/выполненные — отдельным разделом, без
// лишних нажатий". "Сегодня" — такой же всегда видимый раздел, вынесенный
// из "Активных", а не режим просмотра.
function isToday(triggerAt: string | null): boolean {
  if (!triggerAt) return false;
  const t = new Date(triggerAt);
  const now = new Date();
  return t.getFullYear() === now.getFullYear() && t.getMonth() === now.getMonth() && t.getDate() === now.getDate();
}

// Фильтр горизонта для "Активных" (уже без сегодняшних — те в своём
// разделе). Просроченное и без даты не прячем ни при каком горизонте —
// сужение окна должно скрывать только далёкое будущее, а не то, что и так
// требует внимания.
type Horizon = "all" | "3days" | "week";

const HORIZON_LABELS: Record<Horizon, string> = { all: "Все", "3days": "3 дня", week: "Неделя" };

function matchesHorizon(horizon: Horizon, triggerAt: string | null): boolean {
  if (horizon === "all" || !triggerAt) return true;
  const t = new Date(triggerAt).getTime();
  const now = Date.now();
  if (t <= now) return true;
  const days = horizon === "3days" ? 3 : 7;
  return t < now + days * 24 * 3600_000;
}

function formatWhen(value: string): string {
  return new Date(value).toLocaleString(dateLocale, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// resolved_at — независимая ось от trigger_at (реальная жалоба: время
// напоминания прошло не значит, что дело сделано — пользователь всё равно
// считает его активным, пока сам не отметит). Кружок слева — эта отметка,
// не путать с "прочитано" (read_at, влияет только на подсветку/бейдж).
// Клик по самой строке — переход к заметке/пункту списка, если ассистент
// их указал при создании (create_reminder, tools/reminders.py); работает
// и для уже выполненных — вернуться посмотреть, к чему было напоминание.
const SNOOZE_OPTIONS: { preset: SnoozePreset; label: string }[] = [
  { preset: "30m", label: "Через полчаса" },
  { preset: "1h", label: "Через час" },
  { preset: "3h", label: "Через 3 часа" },
  { preset: "tomorrow", label: "Завтра утром" },
  { preset: "week", label: "Через неделю" },
];

// «Отложить» — жалоба 18.10: открытое и не закрытое напоминание висело
// месяцами и больше ни разу о себе не напоминало. Отложенное сработает
// заново (снова придёт в Telegram и колокольчик), а не просто сдвинется.
function SnoozeButton({ notificationId }: { notificationId: string }) {
  const [open, setOpen] = useState(false);
  const snooze = useSnoozeNotification();
  return (
    <div className="relative shrink-0">
      <button
        title="Отложить"
        onClick={() => setOpen((v) => !v)}
        disabled={snooze.isPending}
        className="flex h-7 w-7 items-center justify-center rounded text-subtle hover:bg-muted-hover hover:text-secondary disabled:opacity-50"
      >
        <AlarmClock size={14} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-30 mt-1 w-40 rounded-2xl border bg-surface py-1.5 shadow-lg">
            {SNOOZE_OPTIONS.map((o) => (
              <button
                key={o.preset}
                onClick={() => {
                  setOpen(false);
                  snooze.mutate({ id: notificationId, preset: o.preset });
                }}
                className="block min-h-10 w-full px-4 py-2 text-left text-sm font-semibold text-secondary hover:bg-muted"
              >
                {o.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// Пинг приёма рутины (app/routines.py, макет «Активность с рутиной»,
// 26.10): та же карточка, что у напоминания, но с таймером ожидания и
// кнопками «Дал», «+30 мин», «Делает не я». Отметка закрывает приём у
// всех участников, не только эту строку.
function RoutineDoseRow({
  notification,
  onOpen,
}: {
  notification: Notification;
  onOpen: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
}) {
  const act = useRoutineDoseAction();
  const markRead = useMarkNotificationRead();
  const del = useDeleteNotification();
  const { data: me } = useMe();
  const spaceId = notification.payload.space_id as string | undefined;
  const itemId = notification.payload.item_id as string | undefined;
  const doseId = notification.payload.dose_id as string | undefined;
  const resolved = !!notification.resolved_at;
  const deferred = notification.payload.deferred === true;
  const plannedAt = notification.trigger_at ? new Date(notification.trigger_at) : null;
  const waiting = plannedAt ? Math.max(0, Math.round((Date.now() - plannedAt.getTime()) / 60_000)) : 0;
  const nagCount = Number(notification.payload.nag_count ?? 0);
  const run = (action: "done" | "defer" | "snooze", minutes?: number) => {
    if (!itemId || !doseId) return;
    act.mutate({ routineId: itemId, doseId, action, body: minutes ? { minutes } : undefined });
  };
  const status = resolved
    ? deferred
      ? t("routine.youDeferred")
      : `выполнено ${formatWhen(notification.resolved_at!)}`
    : waiting > 0
      ? `${t("routine.waiting", { n: humanMinutes(waiting, dateLocale) })}${nagCount > 1 ? ` · ${nagCount}` : ""}`
      : plannedAt
        ? `сработает ${formatWhen(notification.trigger_at!)}`
        : formatWhen(notification.created_at);
  const busy = act.isPending;
  const swipeActions = resolved
    ? []
    : [
        { label: t("routine.plus30"), tone: "lime" as const, icon: <AlarmClock size={16} />, onClick: () => run("snooze", 30) },
        { label: t("routine.given"), tone: "dark" as const, icon: <Check size={16} />, onClick: () => run("done") },
      ];

  return (
    <SwipeRow
      actions={swipeActions}
      className={`row-fade-in mx-3 mb-2 shadow-card ${!resolved && waiting > 0 ? "ring-2 ring-warning/70" : !resolved && !notification.read_at ? "ring-1 ring-brand/40" : ""}`}
    >
      <div className="rounded-2xl bg-surface px-3.5 py-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-text">
            <Pill size={18} strokeWidth={2.2} />
          </span>
          <button
            onClick={() => {
              if (!notification.read_at) markRead.mutate(notification.id);
              if (spaceId && itemId) onOpen(spaceId, itemId, undefined, notification.id);
            }}
            disabled={!spaceId || !itemId}
            className="min-w-0 flex-1 text-left"
          >
            <div className={`truncate text-[15px] font-bold ${resolved ? "text-subtle line-through" : "text-primary"}`}>
              {notification.title}
              {plannedAt && <span className="font-extrabold"> · {plannedAt.toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" })}</span>}
            </div>
            {notification.body && <div className="mt-0.5 truncate text-xs text-subtle">{notification.body}</div>}
            <div className={`mt-0.5 text-xs font-semibold ${!resolved && waiting > 0 ? "text-warning" : "text-subtle"}`}>{status}</div>
          </button>
          {!resolved && (
            <button onClick={() => run("done")} disabled={busy} className="h-10 shrink-0 rounded-full bg-nav px-4 text-sm font-extrabold text-lime disabled:opacity-60">
              {t("routine.given")}
            </button>
          )}
          {resolved && (
            <button title="Удалить" onClick={() => del.mutate(notification.id)} disabled={del.isPending} className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-subtle hover:bg-danger/10 hover:text-danger disabled:opacity-50">
              <X size={14} />
            </button>
          )}
        </div>
        {!resolved && (
          <div className="mt-2.5 flex flex-wrap gap-2 pl-[46px]">
            <button onClick={() => run("snooze", 30)} disabled={busy} className="h-8 rounded-full bg-muted px-3 text-xs font-bold text-primary disabled:opacity-60">{t("routine.plus30")}</button>
            <button onClick={() => run("snooze", 60)} disabled={busy} className="h-8 rounded-full bg-muted px-3 text-xs font-bold text-primary disabled:opacity-60">{t("routine.plus60")}</button>
            {me && !deferred && (
              <button onClick={() => run("defer")} disabled={busy} className="h-8 rounded-full bg-muted px-3 text-xs font-bold text-primary disabled:opacity-60">{t("routine.notMe")}</button>
            )}
          </div>
        )}
      </div>
    </SwipeRow>
  );
}

function NotificationRow({
  notification,
  onOpen,
}: {
  notification: Notification;
  onOpen: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
}) {
  const resolve = useResolveNotification();
  const unresolve = useUnresolveNotification();
  const markRead = useMarkNotificationRead();
  const del = useDeleteNotification();
  const snooze = useSnoozeNotification();
  if (notification.type === "routine_dose") return <RoutineDoseRow notification={notification} onOpen={onOpen} />;
  const spaceId = notification.payload.space_id as string | undefined;
  const itemId = notification.payload.item_id as string | undefined;
  const entryId = notification.payload.entry_id as string | undefined;
  const clickable = !!spaceId && !!itemId;
  const resolved = !!notification.resolved_at;
  const overdue = !resolved && !!notification.trigger_at && new Date(notification.trigger_at).getTime() <= Date.now();
  const repeat = repeatLabel(notification.repeat_rule);
  const findText = notification.payload.find as string | undefined;

  // Свайп влево (макет «Активность»): «Завтра» и «Сделано» — те же
  // кнопки, что приходят в Telegram и в сводке.
  const swipeActions = resolved
    ? []
    : [
        ...(notification.trigger_at
          ? [{ label: "Завтра", tone: "lime" as const, icon: <AlarmClock size={16} />, onClick: () => snooze.mutate({ id: notification.id, preset: "tomorrow" }) }]
          : []),
        { label: "Сделано", tone: "dark" as const, icon: <Check size={16} />, onClick: () => resolve.mutate(notification.id) },
      ];

  return (
    <SwipeRow
      actions={swipeActions}
      className={`row-fade-in mx-3 mb-2 shadow-card ${!resolved && !notification.read_at ? "ring-1 ring-brand/40" : ""}`}
    >
    <div className="flex items-start gap-2 rounded-2xl bg-surface px-3.5 py-3">
      <button
        title={resolved ? "Вернуть в активные" : "Отметить выполненным"}
        onClick={() => (resolved ? unresolve.mutate(notification.id) : resolve.mutate(notification.id))}
        disabled={resolve.isPending || unresolve.isPending}
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 disabled:opacity-50 ${
          resolved ? "border-brand bg-brand text-white" : "border-strong text-transparent hover:border-brand"
        }`}
      >
        <Check size={12} />
      </button>
      <button
        onClick={() => {
          if (!notification.read_at) markRead.mutate(notification.id);
          // find — текст, к которому редактор прокрутит (payload
          // напоминания о сроке документа, document_expiry.py). У
          // остальных уведомлений его нет, и тогда заметка просто
          // открывается, как раньше.
          if (clickable) onOpen(spaceId!, itemId!, entryId, notification.id, findText);
        }}
        disabled={!clickable}
        className={`min-w-0 flex-1 text-left ${clickable ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
      >
        <div
          className={`truncate text-[15px] font-bold ${
            resolved ? "text-subtle line-through" : !notification.read_at ? "text-primary" : "text-secondary"
          }`}
        >
          {notification.title}
        </div>
        {notification.body && <div className="mt-0.5 truncate text-xs text-subtle">{notification.body}</div>}
        <div className="mt-0.5 flex items-center gap-1 text-xs text-subtle">
          <CalendarClock size={11} />
          {resolved
            ? `выполнено ${formatWhen(notification.resolved_at!)}`
            : notification.trigger_at
              ? `${overdue ? "должно было сработать" : "сработает"} ${formatWhen(notification.trigger_at)}`
              : formatWhen(notification.created_at)}
          {overdue && (
            <span className="ml-1 rounded-full bg-warning/15 px-1.5 py-0 text-[10px] font-medium text-warning">
              просрочено
            </span>
          )}
          {repeat && (
            // Без этой подписи повторяющееся не отличить от обычного, и
            // "откуда оно опять взялось" выглядит багом.
            <span className="ml-1 inline-flex items-center gap-0.5 text-[10px] text-subtle">
              <Repeat size={10} />
              {repeat}
            </span>
          )}
        </div>
      </button>
      {!resolved && notification.trigger_at && <SnoozeButton notificationId={notification.id} />}
      <button
        title={repeat ? "Удалить и больше не повторять" : "Удалить"}
        onClick={() => del.mutate(notification.id)}
        disabled={del.isPending}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-subtle hover:bg-danger/10 hover:text-danger disabled:opacity-50"
      >
        <X size={14} />
      </button>
    </div>
    </SwipeRow>
  );
}

// Дата/событие, найденное LLM внутри заметки (app/autotag.py) — пассивная
// запись, без resolve/read (нет доставки, нет "выполнено"). Единственное
// действие — открыть заметку или убрать ложное срабатывание.
function DetectedEventRow({
  event,
  onOpen,
}: {
  event: DetectedEvent;
  onOpen: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
}) {
  const dismiss = useDismissDetectedEvent();

  return (
    <div className="row-fade-in mx-3 mb-2 flex items-start gap-2 rounded-2xl bg-brand-soft/60 px-3.5 py-3">
      <Calendar size={14} className="mt-0.5 shrink-0 text-brand" />
      <button
        onClick={() => onOpen(event.space_id, event.item_id)}
        className="min-w-0 flex-1 cursor-pointer text-left hover:opacity-80"
      >
        <div className="truncate text-sm text-secondary">{event.event_title}</div>
        <div className="mt-0.5 flex items-center gap-1 truncate text-xs text-subtle">
          <CalendarClock size={11} />
          {formatWhen(event.event_at)} · {event.item_title}
        </div>
      </button>
      <button
        title="Не событие — убрать"
        onClick={() =>
          dismiss.mutate({ itemId: event.item_id, eventAt: event.event_at, eventTitle: event.event_title })
        }
        disabled={dismiss.isPending}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-subtle hover:bg-danger/10 hover:text-danger disabled:opacity-50"
      >
        <X size={14} />
      </button>
    </div>
  );
}

// Объединённая "лента" для разделов Сегодня/Активные — напоминания и
// найденные в заметках события сортируются и группируются вместе (одна и
// та же ось времени), но остаются разными сущностями с разным набором
// действий (см. NotificationRow/DetectedEventRow выше).
type ActivityEntry =
  | { kind: "notification"; at: string | null; notification: Notification }
  | { kind: "event"; at: string; event: DetectedEvent };

function ActivityEntryRow({
  entry,
  onOpen,
}: {
  entry: ActivityEntry;
  onOpen: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
}) {
  if (entry.kind === "event") {
    return <DetectedEventRow event={entry.event} onOpen={onOpen} />;
  }
  return <NotificationRow notification={entry.notification} onOpen={onOpen} />;
}

function activityEntryKey(entry: ActivityEntry): string {
  return entry.kind === "event" ? `event-${entry.event.item_id}-${entry.event.event_at}` : entry.notification.id;
}

function NotificationsTab({
  onOpen,
}: {
  onOpen: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
}) {
  const { data, isLoading: notificationsLoading } = useAllNotifications();
  const { data: eventsData, isLoading: eventsLoading } = useDetectedEvents();
  const [horizon, setHorizon] = useState<Horizon>("all");

  // Активные — НЕ по времени (прошедшее trigger_at ≠ решено), а по
  // resolved_at: ничего, кроме самого пользователя (или resolve_reminder
  // ассистента), не переводит напоминание в выполненные. "Сегодня" —
  // подмножество активных, вынесенное в свой раздел (см. isToday выше).
  // Найденные в заметках события (useDetectedEvents) подмешиваются в ту же
  // ленту той же осью времени — нет "выполнено", поэтому в "Выполненные"
  // не попадают вовсе.
  const { today, active, resolved } = useMemo(() => {
    const notifs = data ?? [];
    const events = eventsData ?? [];
    const entries: ActivityEntry[] = [
      ...notifs.filter((n) => !n.resolved_at).map((n): ActivityEntry => ({ kind: "notification", at: n.trigger_at, notification: n })),
      ...events.map((e): ActivityEntry => ({ kind: "event", at: e.event_at, event: e })),
    ];
    const byAt = (a: ActivityEntry, b: ActivityEntry) => {
      const at = a.at ? new Date(a.at).getTime() : -Infinity;
      const bt = b.at ? new Date(b.at).getTime() : -Infinity;
      return at - bt;
    };
    const today = entries.filter((e) => isToday(e.at)).sort(byAt);
    const active = entries.filter((e) => !isToday(e.at)).sort(byAt);
    const resolved = notifs
      .filter((n) => n.resolved_at)
      .sort((a, b) => new Date(b.resolved_at!).getTime() - new Date(a.resolved_at!).getTime());
    return { today, active, resolved };
  }, [data, eventsData]);

  const filteredActive = useMemo(() => active.filter((e) => matchesHorizon(horizon, e.at)), [active, horizon]);

  if (notificationsLoading || eventsLoading) {
    return <ListSkeleton rows={6} />;
  }

  if (today.length === 0 && active.length === 0 && resolved.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-8 text-center text-sm text-subtle">
        <BellOff size={24} />
        Пока нет уведомлений
      </div>
    );
  }

  return (
    <div>
      {today.length > 0 && (
        <>
          <div className="px-4 pb-1.5 pt-2 text-[11px] font-extrabold uppercase tracking-wider text-subtle">
            Сегодня
          </div>
          {today.map((e) => (
            <ActivityEntryRow key={activityEntryKey(e)} entry={e} onOpen={onOpen} />
          ))}
        </>
      )}
      {active.length > 0 && (
        <>
          <div className="flex items-center gap-1.5 px-4 pb-1.5 pt-2">
            <span className="mr-0.5 text-[11px] font-extrabold uppercase tracking-wider text-subtle">Активные</span>
            {(Object.keys(HORIZON_LABELS) as Horizon[]).map((h) => (
              <button
                key={h}
                onClick={() => setHorizon(h)}
                className={`h-7 rounded-full px-2.5 text-[11px] font-bold ${
                  horizon === h ? "bg-accent text-on-accent" : "bg-surface text-secondary shadow-card hover:bg-muted"
                }`}
              >
                {HORIZON_LABELS[h]}
              </button>
            ))}
          </div>
          {/* key={horizon} на обёртке — чтобы смена горизонта («Все» /
              «3 дня» / «Неделя») переигрывала анимацию строк. Жалоба
              владельца 12.10: «переключение горизонта активности не
              делает анимации так же».

              Без обёртки строки, попавшие в оба среза, React
              переиспользовал бы по их key — и список менялся бы рывком:
              часть строк исчезает, остальные стоят на месте. С новой
              обёрткой узлы строк создаются заново, и срез приезжает
              целиком. */}
          <div key={horizon} className="row-fade-in">
            {filteredActive.map((e) => (
              <ActivityEntryRow key={activityEntryKey(e)} entry={e} onOpen={onOpen} />
            ))}
          </div>
        </>
      )}
      {resolved.length > 0 && (
        <>
          <div className="px-4 pb-1.5 pt-2 text-[11px] font-extrabold uppercase tracking-wider text-subtle">
            Выполненные
          </div>
          {resolved.map((n) => (
            <NotificationRow key={n.id} notification={n} onOpen={onOpen} />
          ))}
        </>
      )}
    </div>
  );
}

interface RecentEntry {
  kind: "item" | "dialog";
  id: string;
  spaceId: string;
  spaceName: string;
  title: string;
  materialType: string;
  updatedAt: string;
}

const ITEM_ICONS: Record<string, typeof StickyNote> = { note: StickyNote, list: ListChecks, ticket: Sparkles };

function RecentTab({
  onOpenItem,
  onOpenDialog,
}: {
  onOpenItem: (spaceId: string, itemId: string) => void;
  onOpenDialog: (id: string) => void;
}) {
  const { data: items, isLoading: itemsLoading } = useRecentItems();
  const { data: dialogs, isLoading: dialogsLoading } = useDialogs();
  const { data: spaces } = useSpaces();

  const entries = useMemo<RecentEntry[]>(() => {
    const spaceName = (id: string) => spaces?.find((s) => s.id === id)?.name ?? "";
    const itemEntries: RecentEntry[] = (items ?? []).map((i) => ({
      kind: "item",
      id: i.id,
      spaceId: i.space_id,
      spaceName: spaceName(i.space_id),
      title: i.title || "Без названия",
      materialType: i.material_type,
      updatedAt: i.updated_at,
    }));
    const dialogEntries: RecentEntry[] = (dialogs ?? []).map((d) => ({
      kind: "dialog",
      id: d.id,
      spaceId: d.space_id,
      spaceName: d.space_name,
      title: d.title || "Диалог с ассистентом",
      materialType: "dialog",
      updatedAt: d.updated_at,
    }));
    return [...itemEntries, ...dialogEntries]
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
      .slice(0, 40);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, dialogs, spaces]);

  if (itemsLoading || dialogsLoading) {
    return <ListSkeleton rows={6} />;
  }

  if (entries.length === 0) {
    return <div className="px-4 py-6 text-center text-sm font-semibold text-subtle">Пока пусто</div>;
  }

  return (
    <div>
      {entries.map((e) => {
        const Icon = e.kind === "dialog" ? MessageSquare : ITEM_ICONS[e.materialType] ?? StickyNote;
        return (
          <button
            key={`${e.kind}-${e.id}`}
            onClick={() => (e.kind === "dialog" ? onOpenDialog(e.id) : onOpenItem(e.spaceId, e.id))}
            className="row-fade-in mx-3 mb-2 flex w-[calc(100%-1.5rem)] items-center gap-3 rounded-2xl bg-surface p-3 text-left shadow-card hover:shadow-float"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted text-primary">
              <Icon size={18} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[15px] font-extrabold text-primary">{e.title}</div>
              <div className="truncate text-xs font-semibold text-subtle">
                {e.spaceName} · {formatWhen(e.updatedAt)}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export default function ActivityView({
  onBack,
  onOpenReminder,
  onOpenItem,
  onOpenDialog,
}: {
  onBack: () => void;
  onOpenReminder: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
  onOpenItem: (spaceId: string, itemId: string) => void;
  onOpenDialog: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("notifications");

  // Направление скольжения. «Уведомления» слева, «Недавнее» справа —
  // переход вправо приезжает справа, обратный слева, как при листании.
  // Жалоба владельца 12.10: «перехожу на недавние вкладку, а анимации
  // перехода скольжения слева направо и наоборот нет».
  const slide = tab === "recent" ? "tab-slide-forward" : "tab-slide-back";

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex items-center gap-3 p-3 pb-1">
        <button
          onClick={onBack}
          aria-label="Назад"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card lg:hidden"
        >
          <ChevronLeft size={20} strokeWidth={2.4} />
        </button>
        <h1 className="text-2xl font-extrabold tracking-tight text-primary lg:text-lg">{t("nav.activity")}</h1>
      </div>
      <div className="mx-3 mb-2 mt-2 grid grid-cols-2 gap-1 rounded-2xl bg-muted p-1">
        <button
          aria-pressed={tab === "notifications"}
          onClick={() => setTab("notifications")}
          className={`flex h-10 items-center justify-center gap-1.5 rounded-xl text-sm font-bold transition-colors ${
            tab === "notifications" ? "bg-surface text-primary shadow-card" : "text-secondary"
          }`}
        >
          <Bell size={14} /> Уведомления
        </button>
        <button
          aria-pressed={tab === "recent"}
          onClick={() => setTab("recent")}
          className={`flex h-10 items-center justify-center gap-1.5 rounded-xl text-sm font-bold transition-colors ${
            tab === "recent" ? "bg-surface text-primary shadow-card" : "text-secondary"
          }`}
        >
          <CalendarClock size={14} /> Недавнее
        </button>
      </div>
      {/* key={tab} обязателен: без него React переиспользует узел при
          смене вкладки, и CSS-анимация не переигрывается — класс уже
          висит на том же элементе. С key узел новый, анимация идёт с
          начала (тот же приём, что у message-fade-in в чате). */}
      <div key={tab} className={`flex-1 overflow-y-auto ${slide}`}>
        {tab === "notifications" ? <NotificationsTab onOpen={onOpenReminder} /> : <RecentTab onOpenItem={onOpenItem} onOpenDialog={onOpenDialog} />}
      </div>
    </div>
  );
}
