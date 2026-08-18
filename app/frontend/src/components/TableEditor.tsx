import { FormEvent, useEffect, useState } from "react";
import { ChevronLeft, Download, Plus, Trash2, X } from "lucide-react";
import {
  useAddTableColumn,
  useAddTableRow,
  useDeleteItem,
  useDeleteTableColumn,
  useDeleteTableRow,
  useTable,
  useUpdateItem,
  useUpdateTableColumn,
  useUpdateTableRow,
} from "../api/hooks";
import type { TableColumn } from "../api/types";
import { useTableSync } from "../lib/useTableSync";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

const COLUMN_TYPES: { value: string; label: string }[] = [
  { value: "text", label: "Текст" },
  { value: "number", label: "Число" },
  { value: "checkbox", label: "Отметка" },
];

function ColumnHeaderCell({
  column,
  onRename,
  onTypeChange,
  onDelete,
}: {
  column: TableColumn;
  onRename: (name: string) => void;
  onTypeChange: (type: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(column.name);
  useEffect(() => setName(column.name), [column.name]);

  function save() {
    const trimmed = name.trim();
    if (trimmed && trimmed !== column.name) onRename(trimmed);
    else setName(column.name);
    setEditing(false);
  }

  return (
    <th className="whitespace-nowrap border-b bg-slate-50 px-2 py-1.5 text-left text-xs font-medium text-slate-600">
      <div className="flex items-center gap-1">
        {editing ? (
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            className="min-w-0 flex-1 rounded border px-1 py-0.5 text-xs"
          />
        ) : (
          <button onClick={() => setEditing(true)} className="min-w-0 flex-1 truncate text-left hover:text-slate-900">
            {column.name}
          </button>
        )}
        <select
          value={column.type}
          onChange={(e) => onTypeChange(e.target.value)}
          className="shrink-0 rounded border-none bg-transparent text-xs text-slate-400 outline-none"
        >
          {COLUMN_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <button onClick={onDelete} title="Удалить столбец" className="shrink-0 text-slate-300 hover:text-red-600">
          <X size={13} />
        </button>
      </div>
    </th>
  );
}

function RowCell({
  column,
  value,
  onChange,
}: {
  column: TableColumn;
  value: string;
  onChange: (value: string) => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);

  if (column.type === "checkbox") {
    return (
      <td className="border-b px-2 py-1">
        <input
          type="checkbox"
          checked={value === "true"}
          onChange={(e) => onChange(e.target.checked ? "true" : "false")}
          className="h-4 w-4 accent-slate-900"
        />
      </td>
    );
  }
  return (
    <td className="border-b px-2 py-1">
      <input
        type={column.type === "number" ? "number" : "text"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text !== value && onChange(text)}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        className="w-full min-w-[6rem] border-none bg-transparent text-sm outline-none"
      />
    </td>
  );
}

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
  useTableSync(itemId);

  const updateItem = useUpdateItem();
  const deleteItem = useDeleteItem(table?.space_id);
  const addColumn = useAddTableColumn(itemId);
  const updateColumn = useUpdateTableColumn(itemId);
  const deleteColumn = useDeleteTableColumn(itemId);
  const addRow = useAddTableRow(itemId);
  const updateRow = useUpdateTableRow(itemId);
  const deleteRow = useDeleteTableRow(itemId);

  const [title, setTitle] = useState("");
  const [syncedId, setSyncedId] = useState<string | null>(null);
  const [newColumnName, setNewColumnName] = useState("");
  const [addingColumn, setAddingColumn] = useState(false);
  const [newRow, setNewRow] = useState<Record<string, string>>({});
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

  async function submitNewColumn(e: FormEvent) {
    e.preventDefault();
    const name = newColumnName.trim();
    if (!name || addColumn.isPending) return;
    setNewColumnName("");
    setAddingColumn(false);
    await addColumn.mutateAsync(name);
  }

  async function submitNewRow(e: FormEvent) {
    e.preventDefault();
    if (addRow.isPending) return;
    const cells = Object.fromEntries(Object.entries(newRow).filter(([, v]) => v.trim() !== ""));
    if (Object.keys(cells).length === 0) return;
    setNewRow({});
    await addRow.mutateAsync(cells);
  }

  if (!table) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 lg:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          placeholder="Название таблицы"
          className="min-w-0 flex-1 truncate border-none bg-transparent text-sm font-medium text-slate-900 outline-none"
        />
        <a
          href={`/api/tables/${table.id}/export.csv`}
          title="Экспорт в CSV"
          className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
        >
          <Download size={15} />
        </a>
        <button
          title="Удалить таблицу"
          onClick={() => setConfirmingDelete(true)}
          className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-red-600"
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {table.columns.length === 0 ? (
          <div className="p-3 text-sm text-slate-400">Пока нет ни одного столбца — добавьте первый ниже</div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {table.columns.map((col) => (
                  <ColumnHeaderCell
                    key={col.id}
                    column={col}
                    onRename={(name) => updateColumn.mutate({ columnId: col.id, name, type: col.type })}
                    onTypeChange={(type) => updateColumn.mutate({ columnId: col.id, name: col.name, type })}
                    onDelete={() => deleteColumn.mutate(col.id)}
                  />
                ))}
                <th className="w-8 border-b bg-slate-50" />
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={row.id} className="group hover:bg-slate-50">
                  {table.columns.map((col) => (
                    <RowCell
                      key={col.id}
                      column={col}
                      value={row.cells[col.id] ?? ""}
                      onChange={(value) => updateRow.mutate({ rowId: row.id, cells: { [col.id]: value } })}
                    />
                  ))}
                  <td className="border-b px-1 py-1 text-right">
                    <button
                      onClick={() => deleteRow.mutate(row.id)}
                      title="Удалить строку"
                      className="text-slate-300 hover:text-red-600"
                    >
                      <X size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {addingColumn ? (
          <form onSubmit={submitNewColumn} className="mt-2 flex gap-1">
            <input
              autoFocus
              value={newColumnName}
              onChange={(e) => setNewColumnName(e.target.value)}
              placeholder="Название столбца"
              className="w-full max-w-xs rounded border px-2 py-1 text-sm"
            />
            <button
              type="submit"
              disabled={addColumn.isPending}
              className="flex shrink-0 items-center justify-center gap-1 rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-50"
            >
              {addColumn.isPending ? <Spinner size={12} /> : "OK"}
            </button>
            <button
              type="button"
              onClick={() => {
                setNewColumnName("");
                setAddingColumn(false);
              }}
              title="Отменить"
              className="flex shrink-0 items-center justify-center rounded border px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
            >
              <X size={14} />
            </button>
          </form>
        ) : (
          <button
            onClick={() => setAddingColumn(true)}
            className="mt-2 flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700"
          >
            <Plus size={12} /> Столбец
          </button>
        )}
      </div>

      {table.columns.length > 0 && (
        <form onSubmit={submitNewRow} className="flex flex-wrap gap-2 border-t p-3">
          {table.columns.map((col) => (
            <input
              key={col.id}
              value={newRow[col.id] ?? ""}
              onChange={(e) => setNewRow((prev) => ({ ...prev, [col.id]: e.target.value }))}
              placeholder={col.name}
              className="min-w-[7rem] flex-1 rounded border px-3 py-2 text-sm"
            />
          ))}
          <button
            type="submit"
            disabled={addRow.isPending}
            className="flex shrink-0 items-center justify-center rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {addRow.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
          </button>
        </form>
      )}

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
