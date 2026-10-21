import { FormEvent, useEffect, useState } from "react";
import { LayoutGrid, Plus, Table2, X } from "lucide-react";
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
    <th className="whitespace-nowrap border-b bg-muted px-3 py-2 text-left text-xs font-extrabold uppercase tracking-wide text-subtle">
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
      <td className="border-b px-3 py-1.5">
        <input
          type="checkbox"
          checked={value === "true"}
          onChange={(e) => onChange(e.target.checked ? "true" : "false")}
          className="h-5 w-5 accent-brand"
        />
      </td>
    );
  }
  return (
    <td className="border-b px-3 py-1.5">
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

// Та же ячейка, но внутри карточки строки (вид «карточки» на телефоне,
// макет «Таблица», 21.10): подпись столбца сверху, значение под ней.
function CardCell({
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
  return (
    <label className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate text-[11px] font-extrabold uppercase tracking-wide text-subtle">{column.name}</span>
      {column.type === "checkbox" ? (
        <input
          type="checkbox"
          checked={value === "true"}
          onChange={(e) => onChange(e.target.checked ? "true" : "false")}
          className="h-5 w-5 accent-brand"
        />
      ) : (
        <input
          type={column.type === "number" ? "number" : "text"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => text !== value && onChange(text)}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          placeholder="—"
          className="w-full border-none bg-transparent text-[15px] font-semibold text-primary outline-none"
        />
      )}
    </label>
  );
}

// Самодостаточный грид — принимает только tableId и сам тянет данные/шлёт
// мутации. Общий и для standalone-страницы (TableEditor.tsx), и для
// embed-карточки в заметке (TableEmbedCard.tsx) — обе точки входа рисуют
// один и тот же живой грид, ничего не дублируя.
export default function TableGrid({ tableId }: { tableId: string }) {
  const { data: table } = useTable(tableId);
  useTableSync(tableId);
  // На узком экране таблица с несколькими столбцами не влезает — строки
  // показываются карточками, обычный грид включается кнопкой. Стартовое
  // значение — по ширине экрана при монтировании; переключение не
  // запоминается нарочно: это способ посмотреть, а не настройка.
  const [view, setView] = useState<"cards" | "grid">(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(max-width: 639px)").matches
      ? "cards"
      : "grid",
  );

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
      {table.columns.length > 0 && (
        <div className="mb-2 flex justify-end">
          <button
            type="button"
            onClick={() => setView((v) => (v === "cards" ? "grid" : "cards"))}
            className="flex h-9 items-center gap-1.5 rounded-full bg-muted px-3 text-xs font-bold text-secondary hover:bg-muted-hover"
          >
            {view === "cards" ? <Table2 size={14} /> : <LayoutGrid size={14} />}
            {view === "cards" ? "Таблицей" : "Карточками"}
          </button>
        </div>
      )}
      {table.columns.length === 0 ? (
        <div className="p-3 text-sm text-subtle">Пока нет ни одного столбца — добавьте первый ниже</div>
      ) : view === "cards" ? (
        <div className="space-y-2">
          {table.rows.length === 0 && <div className="p-3 text-sm text-subtle">Пока нет строк — добавьте первую ниже</div>}
          {table.rows.map((row) => (
            <div key={row.id} className="relative rounded-2xl bg-surface p-3.5 pr-10 shadow-card">
              <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                {table.columns.map((col) => (
                  <CardCell
                    key={col.id}
                    column={col}
                    value={row.cells[col.id] ?? ""}
                    onChange={(value) => updateRow.mutate({ rowId: row.id, cells: { [col.id]: value } })}
                  />
                ))}
              </div>
              <button
                onClick={() => deleteRow.mutate(row.id)}
                title="Удалить строку"
                className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-lg text-subtle hover:bg-muted hover:text-danger"
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl bg-surface shadow-card">
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
            className="flex shrink-0 items-center justify-center gap-1 rounded bg-accent px-2 py-1 text-xs text-on-accent disabled:opacity-50"
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
          className="mt-2 flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-bold text-subtle hover:bg-muted hover:text-secondary"
        >
          <Plus size={14} /> Столбец
        </button>
      )}

      {table.columns.length > 0 && (
        <form onSubmit={submitNewRow} className="mt-3 flex flex-wrap gap-2 rounded-2xl bg-muted p-2">
          {table.columns.map((col) => (
            <input
              key={col.id}
              value={newRow[col.id] ?? ""}
              onChange={(e) => setNewRow((prev) => ({ ...prev, [col.id]: e.target.value }))}
              placeholder={col.name}
              className="h-11 min-w-[7rem] flex-1 rounded-xl border-0 bg-surface px-3 text-sm outline-none focus:ring-2 focus:ring-brand/40"
            />
          ))}
          <button
            type="submit"
            aria-label="Добавить строку"
            disabled={addRow.isPending}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent text-on-accent disabled:opacity-50"
          >
            {addRow.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
          </button>
        </form>
      )}
    </div>
  );
}
