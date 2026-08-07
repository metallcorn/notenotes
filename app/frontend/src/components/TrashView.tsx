import { useState } from "react";
import { ChevronLeft, RotateCcw, Trash2 } from "lucide-react";
import { usePermanentDeleteItem, useRestoreItem, useTrash } from "../api/hooks";
import type { Item } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

export default function TrashView({ spaceId, onBack }: { spaceId: string | undefined; onBack: () => void }) {
  const { data: items, isLoading } = useTrash(spaceId);
  const restore = useRestoreItem(spaceId);
  const permanentDelete = usePermanentDeleteItem(spaceId);
  const [deleting, setDeleting] = useState<Item | null>(null);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex items-center gap-1 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 md:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="text-sm font-medium text-slate-900">Корзина</div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {isLoading && <div className="p-4 text-sm text-slate-400">Загрузка…</div>}
        {!isLoading && (items ?? []).length === 0 && <div className="p-4 text-sm text-slate-400">Корзина пуста</div>}
        {(items ?? []).map((item) => (
          <div key={item.id} className="flex items-center justify-between gap-2 border-b px-4 py-3">
            <div className="min-w-0">
              <div className="truncate text-sm text-slate-900">{item.title || "Без названия"}</div>
              <div className="truncate text-xs text-slate-400">
                удалено {item.deleted_at ? new Date(item.deleted_at).toLocaleString("ru-RU") : ""}
              </div>
            </div>
            <div className="flex shrink-0 gap-1">
              <button
                title="Восстановить"
                onClick={() => restore.mutate(item.id)}
                disabled={restore.isPending}
                className="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100 disabled:opacity-50"
              >
                {restore.isPending ? <Spinner size={14} /> : <RotateCcw size={16} />}
              </button>
              <button
                title="Удалить навсегда"
                onClick={() => setDeleting(item)}
                className="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-red-50 hover:text-red-600"
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
    </div>
  );
}
