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
      <div className="flex items-center gap-1 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-subtle lg:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="flex-1 text-sm font-medium text-primary">{t("nav.trash")}</div>
        {hasItems && (
          <button
            onClick={() => setConfirmingEmpty(true)}
            className="rounded px-2 py-1 text-xs text-danger hover:bg-danger/10"
          >
            Очистить корзину
          </button>
        )}
      </div>
      {hasItems && (
        <div className="border-b bg-muted px-4 py-1.5 text-xs text-subtle">
          Удаляется навсегда через 30 дней
        </div>
      )}
      <div className="flex-1 overflow-y-auto">
        {isLoading && <ListSkeleton rows={5} withIcon={false} />}
        {!isLoading && (items ?? []).length === 0 && <div className="p-4 text-sm text-subtle">Корзина пуста</div>}
        {(items ?? []).map((item) => (
          <div key={item.id} className="row-fade-in flex items-center justify-between gap-2 border-b px-4 py-3">
            <div className="min-w-0">
              <div className="truncate text-sm text-primary">{item.title || "Без названия"}</div>
              <div className="truncate text-xs text-subtle">
                удалено {item.deleted_at ? new Date(item.deleted_at).toLocaleString(dateLocale) : ""}
              </div>
            </div>
            <div className="flex shrink-0 gap-1">
              <button
                title="Восстановить"
                onClick={() => restore.mutate(item.id)}
                disabled={restore.isPending}
                className="flex h-8 w-8 items-center justify-center rounded text-subtle hover:bg-muted-hover disabled:opacity-50"
              >
                {restore.isPending ? <Spinner size={14} /> : <RotateCcw size={16} />}
              </button>
              <button
                title="Удалить навсегда"
                onClick={() => setDeleting(item)}
                className="flex h-8 w-8 items-center justify-center rounded text-subtle hover:bg-danger/10 hover:text-danger"
              >
                <Trash2 size={16} />
              </button>
            </div>
          </div>
        ))}
      </div>

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
