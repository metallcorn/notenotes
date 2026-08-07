import { FormEvent, useEffect, useState } from "react";
import { ChevronLeft, Plus, Trash2, X } from "lucide-react";
import { useAddListEntry, useDeleteItem, useDeleteListEntry, useList, useUpdateItem, useUpdateListEntry } from "../api/hooks";
import type { ListEntry } from "../api/types";
import { useListSync } from "../lib/useListSync";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

function ListEntryRow({
  entry,
  onToggle,
  onTextChange,
  onDelete,
}: {
  entry: ListEntry;
  onToggle: (checked: boolean) => void;
  onTextChange: (text: string) => void;
  onDelete: () => void;
}) {
  const [text, setText] = useState(entry.text);

  useEffect(() => setText(entry.text), [entry.text]);

  function saveText() {
    const trimmed = text.trim();
    if (trimmed && trimmed !== entry.text) onTextChange(trimmed);
    else if (!trimmed) setText(entry.text);
  }

  return (
    <li className="group flex items-center gap-2 rounded px-1 py-1.5 hover:bg-slate-50">
      <input
        type="checkbox"
        checked={entry.checked}
        onChange={(e) => onToggle(e.target.checked)}
        className="h-4 w-4 shrink-0 accent-slate-900"
      />
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={saveText}
        className={`min-w-0 flex-1 border-none bg-transparent text-sm outline-none ${
          entry.checked ? "text-slate-400 line-through" : "text-slate-900"
        }`}
      />
      <button
        onClick={onDelete}
        title="Удалить пункт"
        className="flex h-6 w-6 shrink-0 items-center justify-center text-slate-300 hover:text-red-600"
      >
        <X size={14} />
      </button>
    </li>
  );
}

export default function ListEditor({
  itemId,
  onDeleted,
  onBack,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
}) {
  const { data: list } = useList(itemId);
  useListSync(itemId);

  const updateItem = useUpdateItem();
  const deleteItem = useDeleteItem(list?.space_id);
  const addEntry = useAddListEntry(itemId);
  const updateEntry = useUpdateListEntry(itemId);
  const deleteEntry = useDeleteListEntry(itemId);

  const [title, setTitle] = useState("");
  const [newEntryText, setNewEntryText] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [syncedId, setSyncedId] = useState<string | null>(null);

  useEffect(() => {
    if (list && syncedId !== list.id) {
      setTitle(list.title);
      setSyncedId(list.id);
    }
  }, [list, syncedId]);

  function saveTitle() {
    if (list && title.trim() && title !== list.title) {
      updateItem.mutate({ id: list.id, title: title.trim() });
    }
  }

  async function handleAddEntry(e: FormEvent) {
    e.preventDefault();
    const text = newEntryText.trim();
    if (!text || addEntry.isPending) return;
    setNewEntryText("");
    await addEntry.mutateAsync(text);
  }

  if (!list) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <Spinner />
      </div>
    );
  }

  const doneCount = list.entries.filter((e) => e.checked).length;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 md:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          placeholder="Название списка"
          className="min-w-0 flex-1 truncate border-none bg-transparent text-sm font-medium text-slate-900 outline-none"
        />
        {list.entries.length > 0 && (
          <span className="shrink-0 text-xs text-slate-400">
            {doneCount}/{list.entries.length}
          </span>
        )}
        <button
          title="Удалить список"
          onClick={() => setConfirmingDelete(true)}
          className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-red-600"
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {list.entries.length === 0 ? (
          <div className="p-3 text-sm text-slate-400">Пока пусто — добавь первый пункт</div>
        ) : (
          <ul className="space-y-0.5">
            {list.entries.map((entry) => (
              <ListEntryRow
                key={entry.id}
                entry={entry}
                onToggle={(checked) => updateEntry.mutate({ entryId: entry.id, checked })}
                onTextChange={(text) => updateEntry.mutate({ entryId: entry.id, text })}
                onDelete={() => deleteEntry.mutate(entry.id)}
              />
            ))}
          </ul>
        )}
      </div>

      <form onSubmit={handleAddEntry} className="flex gap-2 border-t p-3">
        <input
          value={newEntryText}
          onChange={(e) => setNewEntryText(e.target.value)}
          placeholder="Новый пункт…"
          className="flex-1 rounded border px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={addEntry.isPending || !newEntryText.trim()}
          className="flex shrink-0 items-center justify-center rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {addEntry.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
        </button>
      </form>

      {confirmingDelete && (
        <ConfirmDialog
          title={`Удалить список «${list.title || "без названия"}»? Он переместится в корзину.`}
          danger
          onConfirm={() => {
            deleteItem.mutate(list.id);
            setConfirmingDelete(false);
            onDeleted();
          }}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </div>
  );
}
