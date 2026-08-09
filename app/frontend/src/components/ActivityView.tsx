import { useMemo, useState } from "react";
import { Bell, BellOff, CalendarClock, Check, ChevronLeft, ListChecks, MessageSquare, Sparkles, StickyNote, X } from "lucide-react";
import {
  useAllNotifications,
  useDeleteNotification,
  useDialogs,
  useMarkNotificationRead,
  useRecentItems,
  useResolveNotification,
  useSpaces,
  useUnresolveNotification,
} from "../api/hooks";
import type { Notification } from "../api/types";
import Spinner from "./Spinner";

type Tab = "notifications" | "recent";

function formatWhen(value: string): string {
  return new Date(value).toLocaleString("ru-RU", {
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
function NotificationRow({
  notification,
  onOpen,
}: {
  notification: Notification;
  onOpen: (spaceId: string, itemId: string, entryId?: string) => void;
}) {
  const resolve = useResolveNotification();
  const unresolve = useUnresolveNotification();
  const markRead = useMarkNotificationRead();
  const del = useDeleteNotification();
  const spaceId = notification.payload.space_id as string | undefined;
  const itemId = notification.payload.item_id as string | undefined;
  const entryId = notification.payload.entry_id as string | undefined;
  const clickable = !!spaceId && !!itemId;
  const resolved = !!notification.resolved_at;
  const overdue = !resolved && !!notification.trigger_at && new Date(notification.trigger_at).getTime() <= Date.now();

  return (
    <div className={`flex items-start gap-2 border-b px-4 py-3 ${!resolved && !notification.read_at ? "bg-slate-50" : ""}`}>
      <button
        title={resolved ? "Вернуть в активные" : "Отметить выполненным"}
        onClick={() => (resolved ? unresolve.mutate(notification.id) : resolve.mutate(notification.id))}
        disabled={resolve.isPending || unresolve.isPending}
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border disabled:opacity-50 ${
          resolved ? "border-green-600 bg-green-600 text-white" : "border-slate-300 text-transparent hover:border-slate-400"
        }`}
      >
        <Check size={12} />
      </button>
      <button
        onClick={() => {
          if (!notification.read_at) markRead.mutate(notification.id);
          if (clickable) onOpen(spaceId!, itemId!, entryId);
        }}
        disabled={!clickable}
        className={`min-w-0 flex-1 text-left ${clickable ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
      >
        <div
          className={`truncate text-sm ${
            resolved ? "text-slate-400 line-through" : !notification.read_at ? "font-medium text-slate-900" : "text-slate-700"
          }`}
        >
          {notification.title}
        </div>
        {notification.body && <div className="mt-0.5 truncate text-xs text-slate-500">{notification.body}</div>}
        <div className="mt-0.5 flex items-center gap-1 text-xs text-slate-400">
          <CalendarClock size={11} />
          {resolved
            ? `выполнено ${formatWhen(notification.resolved_at!)}`
            : notification.trigger_at
              ? `${overdue ? "должно было сработать" : "сработает"} ${formatWhen(notification.trigger_at)}`
              : formatWhen(notification.created_at)}
          {overdue && (
            <span className="ml-1 rounded-full bg-amber-100 px-1.5 py-0 text-[10px] font-medium text-amber-700">
              просрочено
            </span>
          )}
        </div>
      </button>
      <button
        title="Удалить"
        onClick={() => del.mutate(notification.id)}
        disabled={del.isPending}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
      >
        <X size={14} />
      </button>
    </div>
  );
}

function NotificationsTab({
  onOpen,
}: {
  onOpen: (spaceId: string, itemId: string, entryId?: string) => void;
}) {
  const { data, isLoading } = useAllNotifications();

  // Активные — НЕ по времени (прошедшее trigger_at ≠ решено), а по
  // resolved_at: ничего, кроме самого пользователя (или resolve_reminder
  // ассистента), не переводит напоминание в выполненные.
  const { active, resolved } = useMemo(() => {
    const all = data ?? [];
    const active = all
      .filter((n) => !n.resolved_at)
      .sort((a, b) => {
        const at = a.trigger_at ? new Date(a.trigger_at).getTime() : -Infinity;
        const bt = b.trigger_at ? new Date(b.trigger_at).getTime() : -Infinity;
        return at - bt;
      });
    const resolved = all
      .filter((n) => n.resolved_at)
      .sort((a, b) => new Date(b.resolved_at!).getTime() - new Date(a.resolved_at!).getTime());
    return { active, resolved };
  }, [data]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-slate-400">
        <Spinner /> Загрузка…
      </div>
    );
  }

  if (active.length === 0 && resolved.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-8 text-center text-sm text-slate-400">
        <BellOff size={24} />
        Пока нет уведомлений
      </div>
    );
  }

  return (
    <div>
      {active.length > 0 && (
        <>
          <div className="bg-slate-50 px-4 py-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
            Активные
          </div>
          {active.map((n) => (
            <NotificationRow key={n.id} notification={n} onOpen={onOpen} />
          ))}
        </>
      )}
      {resolved.length > 0 && (
        <>
          <div className="bg-slate-50 px-4 py-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
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
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-slate-400">
        <Spinner /> Загрузка…
      </div>
    );
  }

  if (entries.length === 0) {
    return <div className="p-4 text-sm text-slate-400">Пока пусто</div>;
  }

  return (
    <div>
      {entries.map((e) => {
        const Icon = e.kind === "dialog" ? MessageSquare : ITEM_ICONS[e.materialType] ?? StickyNote;
        return (
          <button
            key={`${e.kind}-${e.id}`}
            onClick={() => (e.kind === "dialog" ? onOpenDialog(e.id) : onOpenItem(e.spaceId, e.id))}
            className="flex w-full items-center gap-2.5 border-b px-4 py-2.5 text-left hover:bg-slate-50"
          >
            <Icon size={15} className="shrink-0 text-slate-400" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-slate-900">{e.title}</div>
              <div className="truncate text-xs text-slate-400">
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
  onOpenReminder: (spaceId: string, itemId: string, entryId?: string) => void;
  onOpenItem: (spaceId: string, itemId: string) => void;
  onOpenDialog: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("notifications");

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex items-center gap-1 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 md:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="text-sm font-medium text-slate-900">Активность</div>
      </div>
      <div className="flex border-b">
        <button
          onClick={() => setTab("notifications")}
          className={`flex flex-1 items-center justify-center gap-1.5 py-2 text-sm ${
            tab === "notifications" ? "border-b-2 border-slate-900 font-medium text-slate-900" : "text-slate-500"
          }`}
        >
          <Bell size={14} /> Уведомления
        </button>
        <button
          onClick={() => setTab("recent")}
          className={`flex flex-1 items-center justify-center gap-1.5 py-2 text-sm ${
            tab === "recent" ? "border-b-2 border-slate-900 font-medium text-slate-900" : "text-slate-500"
          }`}
        >
          <CalendarClock size={14} /> Недавнее
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === "notifications" ? <NotificationsTab onOpen={onOpenReminder} /> : <RecentTab onOpenItem={onOpenItem} onOpenDialog={onOpenDialog} />}
      </div>
    </div>
  );
}
