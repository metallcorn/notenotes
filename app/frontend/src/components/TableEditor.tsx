import { useEffect, useState } from "react";
import { ChevronLeft, Download, Trash2 } from "lucide-react";
import { useDeleteItem, useTable, useUpdateItem } from "../api/hooks";
import { t } from "../i18n";
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
      {/* Шапка (макет «Таблица», 21.10): на телефоне — назад, подпись,
          экспорт и удаление 44px, заголовок крупно отдельной строкой. */}
      {/* Одно поле заголовка на оба варианта: на телефоне flex-wrap уносит
          его на отдельную строку под кнопками (order-last), на десктопе оно
          стоит в ряду. Два поля с одним placeholder ломали бы e2e и читалки. */}
      <div className="flex flex-wrap items-center gap-2 p-3 lg:flex-nowrap lg:border-b">
        <button
          onClick={onBack}
          aria-label={t("nav.back")}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card lg:hidden"
        >
          <ChevronLeft size={20} strokeWidth={2.4} />
        </button>
        <div className="min-w-0 flex-1 truncate pl-1 text-[13px] font-bold text-subtle lg:hidden">{t("create.table")}</div>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          placeholder="Название таблицы"
          className="order-last mt-1 w-full min-w-0 border-none bg-transparent px-2 text-[28px] font-extrabold leading-tight tracking-tight text-primary outline-none placeholder:text-subtle lg:order-none lg:mt-0 lg:w-auto lg:flex-1 lg:truncate lg:px-0 lg:text-xl"
        />
        <a
          href={`/api/tables/${table.id}/export.csv`}
          title="Экспорт в CSV"
          aria-label="Экспорт в CSV"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card lg:h-9 lg:w-9 lg:bg-transparent lg:text-subtle lg:shadow-none lg:hover:bg-muted"
        >
          <Download size={18} className="lg:hidden" />
          <Download size={15} className="hidden lg:block" />
        </a>
        <button
          title="Удалить таблицу"
          onClick={() => setConfirmingDelete(true)}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card lg:h-9 lg:w-9 lg:bg-transparent lg:text-subtle lg:shadow-none lg:hover:bg-muted lg:hover:text-danger"
        >
          <Trash2 size={18} className="lg:hidden" />
          <Trash2 size={16} className="hidden lg:block" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3 lg:pt-3">
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
