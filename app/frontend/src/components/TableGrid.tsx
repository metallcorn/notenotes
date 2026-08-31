import { FormEvent, useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import {
  useAddTableColumn,
  useAddTableRow,
  useDeleteTableColumn,
  useDeleteTableRow,
  useTable,
  useUpdateTableColumn,
  useUpdateTableRow,
} from "../api/hooks";
import type { TableColumn } from "../api/types";
import { useTableSync } from "../lib/useTableSync";
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
    <th className="whitespace-nowrap border-b bg-muted px-2 py-1.5 text-left text-xs font-medium text-secondary">
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
          <button onClick={() => setEditing(true)} className="min-w-0 flex-1 truncate text-left hover:text-primary">
            {column.name}
          </button>
        )}
        <select
          value={column.type}
          onChange={(e) => onTypeChange(e.target.value)}
          className="shrink-0 rounded border-none bg-transparent text-xs text-subtle outline-none"
        >
          {COLUMN_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <button onClick={onDelete} title="Удалить столбец" className="shrink-0 text-subtle hover:text-danger">
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
          className="h-4 w-4 accent-accent"
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

// Самодостаточный грид — принимает только tableId и сам тянет данные/шлёт
// мутации. Общий и для standalone-страницы (TableEditor.tsx), и для
// embed-карточки в заметке (TableEmbedCard.tsx) — обе точки входа рисуют
// один и тот же живой грид, ничего не дублируя.
export default function TableGrid({ tableId }: { tableId: string }) {
  const { data: table } = useTable(tableId);
  useTableSync(tableId);

  const addColumn = useAddTableColumn(tableId);
  const updateColumn = useUpdateTableColumn(tableId);
  const deleteColumn = useDeleteTableColumn(tableId);
  const addRow = useAddTableRow(tableId);
  const updateRow = useUpdateTableRow(tableId);
  const deleteRow = useDeleteTableRow(tableId);

  const [newColumnName, setNewColumnName] = useState("");
  const [addingColumn, setAddingColumn] = useState(false);
  const [newRow, setNewRow] = useState<Record<string, string>>({});

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
      <div className="flex items-center justify-center p-6 text-subtle">
        <Spinner />
      </div>
    );
  }

  return (
    <div>
      {table.columns.length === 0 ? (
        <div className="p-3 text-sm text-subtle">Пока нет ни одного столбца — добавьте первый ниже</div>
      ) : (
        <div className="overflow-x-auto">
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
                <th className="w-8 border-b bg-muted" />
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={row.id} className="group hover:bg-muted-hover">
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
                      className="text-subtle hover:text-danger"
                    >
                      <X size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
            className="flex shrink-0 items-center justify-center gap-1 rounded bg-accent px-2 py-1 text-xs text-white disabled:opacity-50"
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
            className="flex shrink-0 items-center justify-center rounded border px-2 py-1 text-xs text-subtle hover:bg-muted-hover"
          >
            <X size={14} />
          </button>
        </form>
      ) : (
        <button
          onClick={() => setAddingColumn(true)}
          className="mt-2 flex items-center gap-1 text-xs text-subtle hover:text-secondary"
        >
          <Plus size={12} /> Столбец
        </button>
      )}

      {table.columns.length > 0 && (
        <form onSubmit={submitNewRow} className="mt-2 flex flex-wrap gap-2 border-t pt-2">
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
            className="flex shrink-0 items-center justify-center rounded bg-accent px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {addRow.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
          </button>
        </form>
      )}
    </div>
  );
}
