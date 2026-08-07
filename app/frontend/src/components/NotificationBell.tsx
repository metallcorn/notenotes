import { useState } from "react";
import { Bell, RefreshCw } from "lucide-react";
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "../api/hooks";

export default function NotificationBell({ updateAvailable }: { updateAvailable: boolean }) {
  const [open, setOpen] = useState(false);
  const { data: notifications } = useNotifications();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();

  const unreadCount = (notifications ?? []).filter((n) => !n.read_at).length + (updateAvailable ? 1 : 0);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        title="Уведомления"
        className="relative flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100"
      >
        <Bell size={16} />
        {unreadCount > 0 && (
          <span className="absolute right-0.5 top-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-red-500 text-[9px] font-medium text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          {/* На мобиле сайдбар — вся ширина экрана, и кнопка (после flex-1
              у UserMenu) оказывается у правого края экрана — right-0 держит
              панель на экране. На десктопе сайдбар всего 256px (w-64) и
              приклеен к левому краю окна — та же кнопка оказывается у
              левого края ЭКРАНА, и right-0 там уводит панель за левый край.
              Нужен разный якорь на разных брейкпоинтах, не один и тот же. */}
          <div className="absolute bottom-full right-0 z-30 mb-1 max-h-96 w-72 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded border bg-white shadow-lg lg:right-auto lg:left-0">
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Уведомления</span>
              {(notifications ?? []).some((n) => !n.read_at) && (
                <button
                  onClick={() => markAllRead.mutate()}
                  className="text-xs text-slate-400 hover:text-slate-700"
                >
                  Прочитать всё
                </button>
              )}
            </div>

            {updateAvailable && (
              <div className="flex items-start gap-2 border-b bg-amber-50 px-3 py-2">
                <RefreshCw size={14} className="mt-0.5 shrink-0 text-amber-600" />
                <div className="flex-1">
                  <div className="text-sm text-slate-800">Доступна новая версия приложения</div>
                  <button
                    onClick={() => window.location.reload()}
                    className="mt-1 rounded bg-slate-900 px-2 py-0.5 text-xs text-white"
                  >
                    Обновить страницу
                  </button>
                </div>
              </div>
            )}

            {(notifications ?? []).length === 0 && !updateAvailable && (
              <div className="p-3 text-sm text-slate-400">Пока пусто</div>
            )}

            {(notifications ?? []).map((n) => (
              <button
                key={n.id}
                onClick={() => !n.read_at && markRead.mutate(n.id)}
                className={`block w-full border-b px-3 py-2 text-left text-sm ${n.read_at ? "text-slate-500" : "bg-slate-50 font-medium text-slate-900"}`}
              >
                <div>{n.title}</div>
                {n.body && <div className="mt-0.5 text-xs font-normal text-slate-500">{n.body}</div>}
                <div className="mt-0.5 text-xs font-normal text-slate-400">
                  {new Date(n.created_at).toLocaleString("ru-RU")}
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
