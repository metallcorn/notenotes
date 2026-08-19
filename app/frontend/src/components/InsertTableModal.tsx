import { useState } from "react";
import { Search, Table as TableIcon } from "lucide-react";
import { useCreateTable, useItems } from "../api/hooks";
import Spinner from "./Spinner";

type Mode = "new" | "existing";

// Первый в приложении picker "выбери существующий item" — все остальные
// вставки в редакторе (картинка, файл, напоминание) генеративные, создают
// новый контент на месте. Здесь два режима сразу: создать таблицу тут же
// или сослаться на уже существующую (та же таблица может быть встроена в
// несколько заметок — TableEmbedCard.tsx синкается по tableId независимо).
export default function InsertTableModal({
  spaceId,
  folderId,
  onInsert,
  onCancel,
}: {
  spaceId: string;
  folderId: string | null;
  onInsert: (tableId: string) => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<Mode>("new");
  const [newTitle, setNewTitle] = useState("");
  const [query, setQuery] = useState("");
  const createTable = useCreateTable();
  const { data: items, isLoading } = useItems(spaceId, undefined, undefined);

  const existingTables = (items ?? []).filter(
    (i) => i.material_type === "table" && i.title.toLowerCase().includes(query.trim().toLowerCase()),
  );

  async function createNew() {
    if (createTable.isPending) return;
    const table = await createTable.mutateAsync({
      space_id: spaceId,
      folder_id: folderId,
      title: newTitle.trim() || undefined,
    });
    onInsert(table.id);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
          <TableIcon size={16} className="text-slate-500" />
          Таблица
        </div>

        <div className="mb-3 flex rounded border p-0.5 text-sm">
          <button
            onClick={() => setMode("new")}
            className={`flex-1 rounded px-2 py-1 ${mode === "new" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
          >
            Новая
          </button>
          <button
            onClick={() => setMode("existing")}
            className={`flex-1 rounded px-2 py-1 ${mode === "existing" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
          >
            Существующая
          </button>
        </div>

        {mode === "new" ? (
          <>
            <label className="mb-4 block">
              <span className="mb-1 block text-xs text-slate-500">Название (необязательно)</span>
              <input
                autoFocus
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && createNew()}
                placeholder="Название таблицы"
                className="w-full rounded border px-2 py-1.5 text-sm outline-none focus:border-slate-400"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={onCancel} className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100">
                Отмена
              </button>
              <button
                onClick={createNew}
                disabled={createTable.isPending}
                className="flex items-center gap-1.5 rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-40"
              >
                {createTable.isPending && <Spinner size={14} className="text-white" />}
                Создать
              </button>
            </div>
          </>
        ) : (
          <>
            <label className="relative mb-2 block">
              <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Поиск по названию…"
                className="w-full rounded border py-1.5 pl-7 pr-2 text-sm outline-none focus:border-slate-400"
              />
            </label>
            <div className="mb-3 max-h-56 overflow-y-auto rounded border">
              {isLoading ? (
                <div className="flex items-center justify-center p-4 text-slate-400">
                  <Spinner size={16} />
                </div>
              ) : existingTables.length === 0 ? (
                <div className="p-3 text-center text-xs text-slate-400">
                  {items && items.length > 0 && query
                    ? "Ничего не найдено"
                    : "В этом спейсе пока нет других таблиц"}
                </div>
              ) : (
                <ul>
                  {existingTables.map((t) => (
                    <li key={t.id}>
                      <button
                        onClick={() => onInsert(t.id)}
                        className="flex w-full items-center gap-2 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-slate-50"
                      >
                        <TableIcon size={13} className="shrink-0 text-slate-400" />
                        <span className="truncate">{t.title || "Без названия"}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex justify-end">
              <button onClick={onCancel} className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100">
                Отмена
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
