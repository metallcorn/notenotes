import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { ChevronLeft, Plus, Trash2, X } from "lucide-react";
import { useAddListEntry, useDeleteItem, useDeleteListEntry, useList, useUpdateItem, useUpdateListEntry } from "../api/hooks";
import type { ListEntry } from "../api/types";
import { useListSync } from "../lib/useListSync";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

// Пункт списка раньше был ВСЕГДА голым <input> — раз это <input value=...>,
// внутри него физически не может быть настоящего <a>, поэтому markdown-
// ссылка [текст](url), которую туда кладёт ассистент (create_list/
// add_list_entry — тексту в entries негде больше стать ссылкой, у списков
// нет своего markdown-рендера, как у заметок), так и оставалась голым
// текстом со скобками — реальная жалоба ("ссылки некликабельные"). Без
// полноценного markdown-редактора: просто вытаскиваем [текст](url) и голые
// http(s)-ссылки регэкспом и рисуем как <a>, обычный текст — как есть.
const _MD_LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
const _BARE_URL_RE = /(https?:\/\/\S+)/g;

function renderEntryText(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  for (const m of text.matchAll(_MD_LINK_RE)) {
    if (m.index! > lastIndex) nodes.push(text.slice(lastIndex, m.index));
    nodes.push(
      <a
        key={key++}
        href={m[2]}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-blue-600 underline hover:text-blue-800"
      >
        {m[1]}
      </a>,
    );
    lastIndex = m.index! + m[0].length;
  }
  const rest = text.slice(lastIndex);
  // Голые http(s)-ссылки (без markdown-обёртки, например когда ассистент
  // просто дописал URL текстом после названия, а не оформил [текст](url))
  // — тем же приёмом, отдельным проходом, чтобы не пересекаться с уже
  // найденными markdown-ссылками выше. Текстом ссылки — ТОЛЬКО домен, не
  // весь URL: реальная жалоба — голый длинный URL как текст ссылки не
  // помещался в строку пункта (особенно на телефоне) и обрезался до
  // нечитаемого/некликабельного огрызка вроде "https:/…".
  let restLast = 0;
  for (const m of rest.matchAll(_BARE_URL_RE)) {
    if (m.index! > restLast) nodes.push(rest.slice(restLast, m.index));
    let label = m[0];
    try {
      label = new URL(m[0]).hostname.replace(/^www\./, "");
    } catch {
      // Некорректный URL — оставляем как есть, не должно происходить, но
      // не пытаемся падать на этом.
    }
    nodes.push(
      <a
        key={key++}
        href={m[0]}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-blue-600 underline hover:text-blue-800"
      >
        {label}
      </a>,
    );
    restLast = m.index! + m[0].length;
  }
  if (restLast < rest.length) nodes.push(rest.slice(restLast));
  return nodes;
}

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
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setText(entry.text), [entry.text]);

  function saveText() {
    const trimmed = text.trim();
    if (trimmed && trimmed !== entry.text) onTextChange(trimmed);
    else if (!trimmed) setText(entry.text);
    setEditing(false);
  }

  const hasLink = _MD_LINK_RE.test(entry.text) || _BARE_URL_RE.test(entry.text);
  // .test() на regexp с флагом /g двигает lastIndex — сбрасываем, иначе
  // следующий вызов hasLink для того же текста будет случайно false.
  _MD_LINK_RE.lastIndex = 0;
  _BARE_URL_RE.lastIndex = 0;

  return (
    <li
      id={`list-entry-${entry.id}`}
      className="group flex items-center gap-2 rounded px-1 py-1.5 transition-colors duration-500 hover:bg-slate-50"
    >
      <input
        type="checkbox"
        checked={entry.checked}
        onChange={(e) => onToggle(e.target.checked)}
        className="h-4 w-4 shrink-0 accent-slate-900"
      />
      {editing || !hasLink ? (
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={saveText}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className={`min-w-0 flex-1 border-none bg-transparent text-sm outline-none ${
            entry.checked ? "text-slate-400 line-through" : "text-slate-900"
          }`}
        />
      ) : (
        <div
          onClick={() => setEditing(true)}
          className={`min-w-0 flex-1 cursor-text truncate text-sm ${
            entry.checked ? "text-slate-400 line-through" : "text-slate-900"
          }`}
        >
          {renderEntryText(text)}
        </div>
      )}
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
  highlightEntryId,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
  highlightEntryId?: string | null;
}) {
  const { data: list } = useList(itemId);
  useListSync(itemId);

  // Переход из напоминания (create_reminder) — прокрутить к конкретному
  // пункту и подсветить. highlightedRef, а не просто зависимость от
  // highlightEntryId — иначе каждый refetch списка (поллинг раз в минуту у
  // уведомлений тут ни при чём, но список синкается по WS) переигрывал бы
  // подсветку заново, пока пользователь сидит на этой странице.
  const highlightedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!highlightEntryId || !list) return;
    if (highlightedRef.current === highlightEntryId) return;
    highlightedRef.current = highlightEntryId;
    const el = document.getElementById(`list-entry-${highlightEntryId}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("bg-amber-100");
    setTimeout(() => el.classList.remove("bg-amber-100"), 2500);
  }, [highlightEntryId, list]);

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
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 lg:hidden"
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
