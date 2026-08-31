import { useEffect, useState } from "react";
import { ChevronLeft, Download, Trash2 } from "lucide-react";
import { useDeleteItem, useTable, useUpdateItem } from "../api/hooks";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";
import TableGrid from "./TableGrid";

export default function TableEditor({
  itemId,
  onDeleted,
  onBack,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
}) {
  const { data: table } = useTable(itemId);

  const updateItem = useUpdateItem();
  const deleteItem = useDeleteItem(table?.space_id);

  const [title, setTitle] = useState("");
  const [syncedId, setSyncedId] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  useEffect(() => {
    if (table && syncedId !== table.id) {
      setTitle(table.title);
      setSyncedId(table.id);
    }
  }, [table, syncedId]);

  function saveTitle() {
    if (table && title.trim() && title !== table.title) {
      updateItem.mutate({ id: table.id, title: title.trim() });
    }
  }

  if (!table) {
    return (
      <div className="flex h-full items-center justify-center text-subtle">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-subtle lg:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          placeholder="Название таблицы"
          className="min-w-0 flex-1 truncate border-none bg-transparent text-sm font-medium text-primary outline-none"
        />
        <a
          href={`/api/tables/${table.id}/export.csv`}
          title="Экспорт в CSV"
          className="flex h-8 w-8 shrink-0 items-center justify-center text-subtle hover:text-secondary"
        >
          <Download size={15} />
        </a>
        <button
          title="Удалить таблицу"
          onClick={() => setConfirmingDelete(true)}
          className="flex h-8 w-8 shrink-0 items-center justify-center text-subtle hover:text-danger"
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        <TableGrid tableId={itemId} />
      </div>

      {confirmingDelete && (
        <ConfirmDialog
          title={`Удалить таблицу «${table.title || "без названия"}»? Она переместится в корзину.`}
          danger
          onConfirm={() => {
            deleteItem.mutate(table.id);
            setConfirmingDelete(false);
            onDeleted();
          }}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </div>
  );
}
