import { useState } from "react";
import { ChevronDown, ListChecks, Plus } from "lucide-react";
import { useCreateItem, useCreateList, useItems } from "../api/hooks";
import type { Item } from "../api/types";
import Spinner from "./Spinner";

interface NoteTemplate {
  id: string;
  label: string;
  title: string;
  content: string;
}

// Шаблоны — просто стартовая Markdown-структура, ничего не навязывают:
// пользователь может стереть и переписать как угодно (ТЗ — формат всегда
// Markdown вне зависимости от режима редактирования).
const NOTE_TEMPLATES: NoteTemplate[] = [
  { id: "blank", label: "Пустая заметка", title: "", content: "" },
  {
    id: "meeting",
    label: "Встреча",
    title: "Встреча",
    content: "**Дата:** \n**Участники:** \n\n## Повестка\n\n\n## Итоги и задачи\n\n",
  },
  {
    id: "diary",
    label: "Дневник",
    title: new Date().toLocaleDateString("ru-RU"),
    content: "",
  },
  {
    id: "idea",
    label: "Идея",
    title: "",
    content: "## Проблема\n\n\n## Решение\n\n\n## Следующие шаги\n\n",
  },
];

function NoteTemplateMenu({
  onSelect,
  disabled,
  align,
}: {
  onSelect: (template: NoteTemplate) => void;
  disabled?: boolean;
  align: "top" | "bottom";
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title="Шаблон заметки"
        className={
          align === "top"
            ? "flex h-full items-center justify-center rounded-r border-l border-slate-700 bg-slate-900 px-2 text-white disabled:opacity-50"
            : "flex h-6 w-6 items-center justify-center rounded-full bg-white text-slate-600 shadow ring-1 ring-slate-200 disabled:opacity-50"
        }
      >
        <ChevronDown size={14} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className={`absolute right-0 z-50 w-48 rounded border bg-white py-1 shadow-lg ${
              align === "top" ? "top-full mt-1" : "bottom-full mb-1"
            }`}
          >
            {NOTE_TEMPLATES.map((t) => (
              <button
                key={t.id}
                onClick={() => {
                  setOpen(false);
                  onSelect(t);
                }}
                className="block w-full px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
              >
                {t.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function previewText(content: string): string {
  return content
    .replace(/<[^>]+>/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[#>*_`~-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
}

function listProgress(content: string): string {
  const lines = content.split("\n").filter(Boolean);
  if (lines.length === 0) return "Пусто";
  const done = lines.filter((l) => l.startsWith("[x]")).length;
  return `${done}/${lines.length} выполнено`;
}

function NoteRow({ item, selected, onSelect }: { item: Item; selected: boolean; onSelect: (id: string) => void }) {
  const isList = item.material_type === "list";
  const preview = isList ? listProgress(item.content) : previewText(item.content);
  return (
    <li>
      <button
        onClick={() => onSelect(item.id)}
        className={`block w-full border-b px-3 py-2 text-left ${selected ? "bg-slate-100" : "hover:bg-slate-50"}`}
      >
        <div className="flex items-center gap-1.5 truncate text-sm font-medium">
          {isList ? (
            <ListChecks size={13} className="shrink-0 text-slate-400" />
          ) : (
            item.icon && <span>{item.icon}</span>
          )}
          <span className="truncate" style={item.color ? { color: item.color } : undefined}>
            {item.title || "Без названия"}
          </span>
        </div>
        {preview && <div className="mt-0.5 truncate text-xs text-slate-500">{preview}</div>}
        <div className="mt-0.5 truncate text-xs text-slate-400">
          {new Date(item.updated_at).toLocaleString("ru-RU")}
          {item.tags.length > 0 && " · " + item.tags.map((t) => `#${t.name}`).join(" ")}
        </div>
      </button>
    </li>
  );
}

export default function NoteList({
  spaceId,
  folderId,
  tagId,
  selectedId,
  onSelect,
}: {
  spaceId: string;
  folderId: string | null;
  tagId: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const effectiveFolderId = tagId ? null : folderId;
  const { data: items, isLoading } = useItems(spaceId, effectiveFolderId, tagId);
  const createItem = useCreateItem();
  const createList = useCreateList();

  async function createNote(template?: NoteTemplate) {
    const targetFolderId = effectiveFolderId === "root" ? null : effectiveFolderId;
    const item = await createItem.mutateAsync({
      space_id: spaceId,
      folder_id: targetFolderId,
      title: template?.title ?? "",
      content: template?.content ?? "",
    });
    onSelect(item.id);
  }

  async function createNewList() {
    const targetFolderId = effectiveFolderId === "root" ? null : effectiveFolderId;
    const list = await createList.mutateAsync({ space_id: spaceId, folder_id: targetFolderId });
    onSelect(list.id);
  }

  const pinned = (items ?? []).filter((i) => i.pinned);
  const rest = (items ?? []).filter((i) => !i.pinned);

  return (
    <div className="flex h-full flex-col">
      {/* На десктопе — обычные кнопки сверху. На телефоне верх экрана до
          них тянуться неудобно (жалоба с телефона), поэтому там вместо
          них плавающие кнопки снизу-справа — чуть выше кнопки «Отзыв»,
          чтобы не перекрывались. */}
      <div className="hidden gap-2 border-b p-3 md:flex">
        <div className="flex flex-1">
          <button
            onClick={() => createNote()}
            disabled={createItem.isPending}
            className="flex flex-1 items-center justify-center gap-2 rounded-l bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {createItem.isPending && <Spinner />}
            {createItem.isPending ? "Создаём…" : "+ Заметка"}
          </button>
          <NoteTemplateMenu onSelect={createNote} disabled={createItem.isPending} align="top" />
        </div>
        <button
          onClick={createNewList}
          disabled={createList.isPending}
          className="flex flex-1 items-center justify-center gap-2 rounded border border-slate-900 px-3 py-1.5 text-sm font-medium text-slate-900 disabled:opacity-50"
        >
          {createList.isPending && <Spinner />}
          {createList.isPending ? "Создаём…" : "+ Список"}
        </button>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto pb-20 md:pb-0">
        {isLoading && (
          <li className="flex items-center gap-2 p-3 text-sm text-slate-400">
            <Spinner /> Загрузка…
          </li>
        )}
        {!isLoading && (items ?? []).length === 0 && (
          <li className="p-3 text-sm text-slate-400">Здесь пока пусто</li>
        )}
        {pinned.length > 0 && (
          <>
            <li className="bg-slate-50 px-3 py-1 text-xs font-medium uppercase tracking-wide text-slate-400">
              Важное
            </li>
            {pinned.map((item) => (
              <NoteRow key={item.id} item={item} selected={selectedId === item.id} onSelect={onSelect} />
            ))}
          </>
        )}
        {rest.map((item) => (
          <NoteRow key={item.id} item={item} selected={selectedId === item.id} onSelect={onSelect} />
        ))}
      </ul>
      <div className="fixed bottom-20 right-4 z-40 flex flex-col items-end gap-2 md:hidden">
        <button
          onClick={createNewList}
          disabled={createList.isPending}
          title="Новый список"
          className="flex h-11 w-11 items-center justify-center rounded-full bg-white text-slate-900 shadow-lg ring-1 ring-slate-200 disabled:opacity-50"
        >
          {createList.isPending ? <Spinner size={18} /> : <ListChecks size={18} />}
        </button>
        <div className="relative">
          <button
            onClick={() => createNote()}
            disabled={createItem.isPending}
            title="Новая заметка"
            className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-900 text-white shadow-lg disabled:opacity-50"
          >
            {createItem.isPending ? <Spinner size={20} /> : <Plus size={24} />}
          </button>
          <div className="absolute -left-1 -top-1">
            <NoteTemplateMenu onSelect={createNote} disabled={createItem.isPending} align="bottom" />
          </div>
        </div>
      </div>
    </div>
  );
}
