import { useState } from "react";
import { Bell, RefreshCw } from "lucide-react";
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "../api/hooks";
import { dateLocale } from "../i18n";

export default function NotificationBell({
  updateAvailable,
  onOpenReminder,
  placement = "up",
}: {
  updateAvailable: boolean;
  onOpenReminder: (spaceId: string, itemId: string, entryId?: string, notificationId?: string, findText?: string) => void;
  // Вверх — из футера сайдбара на десктопе, вниз — из шапки «Главной».
  placement?: "up" | "down";
}) {
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
        className={`relative flex items-center justify-center rounded-full text-primary hover:bg-muted-hover ${
          placement === "down" ? "h-11 w-11 bg-surface shadow-card" : "h-8 w-8"
        }`}
      >
        <Bell size={placement === "down" ? 20 : 16} />
        {unreadCount > 0 && (
          <span className="absolute right-0.5 top-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-danger text-[9px] font-medium text-white">
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
          <div
            className={`absolute z-30 max-h-96 w-72 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded-2xl border bg-surface shadow-lg ${
              placement === "down" ? "right-0 top-full mt-1" : "bottom-full right-0 mb-1 lg:left-0 lg:right-auto"
            }`}
          >
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-xs font-medium uppercase tracking-wide text-subtle">Уведомления</span>
              {(notifications ?? []).some((n) => !n.read_at) && (
                <button
                  onClick={() => markAllRead.mutate()}
                  className="text-xs text-subtle hover:text-secondary"
                >
                  Прочитать всё
                </button>
              )}
            </div>

            {updateAvailable && (
              <div className="flex items-start gap-2 border-b bg-warning/10 px-3 py-2">
                <RefreshCw size={14} className="mt-0.5 shrink-0 text-warning" />
                <div className="flex-1">
                  <div className="text-sm text-primary">Доступна новая версия приложения</div>
                  <button
                    onClick={() => window.location.reload()}
                    className="mt-1 rounded bg-accent px-2 py-0.5 text-xs text-on-accent"
                  >
                    Обновить страницу
                  </button>
                </div>
              </div>
            )}

            {(notifications ?? []).length === 0 && !updateAvailable && (
              <div className="p-3 text-sm text-subtle">Пока пусто</div>
            )}

            {(notifications ?? []).map((n) => {
              const spaceId = n.payload.space_id as string | undefined;
              const itemId = n.payload.item_id as string | undefined;
              const entryId = n.payload.entry_id as string | undefined;
              return (
                <button
                  key={n.id}
                  onClick={() => {
                    if (!n.read_at) markRead.mutate(n.id);
                    if (spaceId && itemId) {
                      setOpen(false);
                      // find — куда прокрутить внутри заметки (payload
                      // напоминания о сроке). Колокольчик — самый частый
                      // вход в приложении, и без этого аргумента он
                      // единственный не прокручивал бы.
                      onOpenReminder(spaceId, itemId, entryId, n.id, n.payload.find as string | undefined);
                    }
                  }}
                  className={`block w-full border-b px-3 py-2 text-left text-sm ${n.read_at ? "text-subtle" : "bg-muted font-medium text-primary"}`}
                >
                  <div>{n.title}</div>
                  {n.body && <div className="mt-0.5 text-xs font-normal text-subtle">{n.body}</div>}
                  <div className="mt-0.5 text-xs font-normal text-subtle">
                    {new Date(n.created_at).toLocaleString(dateLocale)}
                  </div>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
