import { useState } from "react";
import { ChevronLeft, RotateCcw, Trash2 } from "lucide-react";
import { useEmptyTrash, usePermanentDeleteItem, useRestoreItem, useTrash } from "../api/hooks";
import type { Item } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";
import { ListSkeleton } from "./Skeleton";
import { dateLocale, t } from "../i18n";

export default function TrashView({ spaceId, onBack }: { spaceId: string | undefined; onBack: () => void }) {
  const { data: items, isLoading } = useTrash(spaceId);
  const restore = useRestoreItem(spaceId);
  const permanentDelete = usePermanentDeleteItem(spaceId);
  const emptyTrash = useEmptyTrash(spaceId);
  const [deleting, setDeleting] = useState<Item | null>(null);
  const [confirmingEmpty, setConfirmingEmpty] = useState(false);
  const hasItems = (items ?? []).length > 0;

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
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-extrabold tracking-tight text-primary lg:text-lg">{t("nav.trash")}</h1>
          {hasItems && <div className="text-xs font-semibold text-subtle">Удаляется навсегда через 30 дней</div>}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-3 pt-2">
        {isLoading && <ListSkeleton rows={5} withIcon={false} />}
        {!isLoading && (items ?? []).length === 0 && (
          <div className="px-4 py-6 text-center text-sm font-semibold text-subtle">Корзина пуста</div>
        )}
        {(items ?? []).map((item) => {
          const daysLeft = item.deleted_at
            ? Math.max(0, 30 - Math.floor((Date.now() - new Date(item.deleted_at).getTime()) / 86_400_000))
            : null;
          return (
            <div key={item.id} className="row-fade-in mb-2 flex items-center gap-3 rounded-2xl bg-surface p-3 shadow-card">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[15px] font-extrabold text-secondary">{item.title || "Без названия"}</div>
                <div className={`truncate text-xs font-bold ${daysLeft !== null && daysLeft <= 3 ? "text-danger" : "text-subtle"}`}>
                  {daysLeft !== null ? `осталось ${daysLeft} дн.` : ""}
                  {item.deleted_at ? ` · удалено ${new Date(item.deleted_at).toLocaleDateString(dateLocale)}` : ""}
                </div>
              </div>
              <button
                title="Восстановить"
                onClick={() => restore.mutate(item.id)}
                disabled={restore.isPending}
                className="flex h-10 shrink-0 items-center gap-1.5 rounded-full bg-accent px-3.5 text-[13px] font-extrabold text-on-accent disabled:opacity-50"
              >
                {restore.isPending ? <Spinner size={14} /> : <RotateCcw size={14} />}
                Вернуть
              </button>
              <button
                title="Удалить навсегда"
                onClick={() => setDeleting(item)}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-danger-soft hover:text-danger"
              >
                <Trash2 size={16} />
              </button>
            </div>
          );
        })}
      </div>
      {hasItems && (
        <div className="p-3">
          <button
            onClick={() => setConfirmingEmpty(true)}
            className="h-12 w-full rounded-2xl bg-danger-soft text-[15px] font-extrabold text-danger"
          >
            Очистить корзину
          </button>
        </div>
      )}

      {deleting && (
        <ConfirmDialog
          title={`Удалить «${deleting.title || "заметку"}» навсегда? Это необратимо.`}
          danger
          confirmLabel="Удалить навсегда"
          onConfirm={() => {
            permanentDelete.mutate(deleting.id);
            setDeleting(null);
          }}
          onCancel={() => setDeleting(null)}
        />
      )}

      {confirmingEmpty && (
        <ConfirmDialog
          title="Очистить корзину полностью? Все заметки в ней будут удалены навсегда. Это необратимо."
          danger
          confirmLabel="Очистить корзину"
          onConfirm={() => {
            emptyTrash.mutate();
            setConfirmingEmpty(false);
          }}
          onCancel={() => setConfirmingEmpty(false)}
        />
      )}
    </div>
  );
}
