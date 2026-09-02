import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ListChecks, MessageSquareText, Plus, Table as TableIcon, Trash2 } from "lucide-react";
import {
  useCreateDialog,
  useCreateItem,
  useCreateList,
  useCreateTable,
  useDeleteItem,
  useItems,
  useScopedFolderDialogs,
} from "../api/hooks";
import type { DialogSummary, Item } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

// Тот же портал-в-body паттерн, что только что сделан для FolderMenu в
// FolderTree.tsx — список заметок тоже живёт внутри overflow-y-auto,
// абсолютное позиционирование внутри него так же обрезалось бы.
function FolderDialogPicker({
  anchorRef,
  dialogs,
  onPick,
  onNew,
  onClose,
  onDeleted,
}: {
  anchorRef: RefObject<HTMLButtonElement>;
  dialogs: DialogSummary[];
  onPick: (id: string) => void;
  onNew: () => void;
  onClose: () => void;
  onDeleted: (id: string) => void;
}) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const deleteItem = useDeleteItem(undefined);
  // Реальная жалоба: "эти чаты нельзя удалять почему-то" — тот же паттерн,
  // что уже есть у NoteAssistantModal.tsx/DialogList.tsx для чатов по
  // заметке/общих, просто не добавили сюда же для чатов по папке.
  const [deletingDialog, setDeletingDialog] = useState<DialogSummary | null>(null);

  useEffect(() => {
    if (!anchorRef.current) return;
    const r = anchorRef.current.getBoundingClientRect();
    setPos({ top: r.bottom + 4, left: r.left });
  }, [anchorRef]);

  if (!pos) return null;

  return createPortal(
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        style={{ top: pos.top, left: pos.left, maxWidth: "calc(100vw - 24px)" }}
        className="fixed z-50 max-h-72 w-64 overflow-y-auto rounded border bg-surface py-1 shadow-lg"
      >
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm font-medium text-brand hover:bg-brand/10"
        >
          <Plus size={14} /> Новый диалог
        </button>
        <div className="my-1 border-t" />
        {dialogs.map((d) => (
          <div key={d.id} className="flex items-center gap-1 hover:bg-muted-hover">
            <button onClick={() => onPick(d.id)} className="min-w-0 flex-1 px-3 py-1.5 text-left text-sm text-secondary">
              <div className="truncate">{d.preview || d.title}</div>
              <div className="text-xs text-subtle">{new Date(d.updated_at).toLocaleString("ru-RU")}</div>
            </button>
            <button
              onClick={() => setDeletingDialog(d)}
              title="Удалить диалог"
              className="mr-1 flex h-7 w-7 shrink-0 items-center justify-center text-subtle hover:text-danger"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </div>
      {deletingDialog && (
        <ConfirmDialog
          title={`Удалить диалог «${deletingDialog.preview || deletingDialog.title || "Новый диалог"}»? Он переместится в корзину.`}
          danger
          onConfirm={async () => {
            const id = deletingDialog.id;
            await deleteItem.mutateAsync(id);
            setDeletingDialog(null);
            onDeleted(id);
          }}
          onCancel={() => setDeletingDialog(null)}
        />
      )}
    </>,
    document.body,
  );
}

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

// Портал-в-body — та же причина, что у FolderDialogPicker выше и у
// FolderMenu в FolderTree.tsx: список заметок сам живёт внутри
// overflow-y-auto, а abs-позиционированное меню внутри него частично
// заезжает под соседнюю панель спейсов (реальная жалоба — "+Заметка"
// выпадающий список перекрывается панелью спейсов).
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
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; right?: number; left?: number } | null>(null);

  function toggle() {
    if (!open && triggerRef.current) {
      const r = triggerRef.current.getBoundingClientRect();
      // align="top" — рядом с "+Заметка" в шапке, меню раскрывается вниз.
      // align="bottom" — плавающая кнопка внизу экрана (моб.), раскрывается
      // вверх, иначе упёрлось бы в нижний край вьюпорта.
      setPos(
        align === "top"
          ? { top: r.bottom + 4, right: window.innerWidth - r.right }
          : { bottom: window.innerHeight - r.top + 4, left: r.left },
      );
    }
    setOpen((v) => !v);
  }

  return (
    <>
      <button
        ref={triggerRef}
        onClick={toggle}
        disabled={disabled}
        title="Шаблон заметки"
        className={
          align === "top"
            ? "flex h-full items-center justify-center rounded-r border-l border-strong bg-accent px-2 text-on-accent disabled:opacity-50"
            : "flex h-6 w-6 items-center justify-center rounded-full bg-surface text-secondary shadow ring-1 ring-default disabled:opacity-50"
        }
      >
        <ChevronDown size={14} />
      </button>
      {open &&
        pos &&
        createPortal(
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div style={pos} className="fixed z-50 w-48 rounded border bg-surface py-1 shadow-lg">
              {NOTE_TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  onClick={() => {
                    setOpen(false);
                    onSelect(t);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
                >
                  {t.label}
                </button>
              ))}
            </div>
          </>,
          document.body,
        )}
    </>
  );
}

export function previewText(content: string): string {
  return content
    .replace(/<[^>]+>/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[#>*_`~-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
}

export function listProgress(content: string): string {
  const lines = content.split("\n").filter(Boolean);
  if (lines.length === 0) return "Пусто";
  const done = lines.filter((l) => l.startsWith("[x]")).length;
  return `${done}/${lines.length} выполнено`;
}

function NoteRow({ item, selected, onSelect }: { item: Item; selected: boolean; onSelect: (id: string) => void }) {
  const isList = item.material_type === "list";
  const isTable = item.material_type === "table";
  const preview = isList ? listProgress(item.content) : previewText(item.content);
  return (
    <li>
      <button
        onClick={() => onSelect(item.id)}
        className={`block w-full border-b px-3 py-2 text-left ${selected ? "bg-muted-hover" : "hover:bg-muted-hover"}`}
      >
        <div className="flex items-center gap-1.5 truncate text-sm font-medium">
          {isList ? (
            <ListChecks size={13} className="shrink-0 text-subtle" />
          ) : isTable ? (
            <TableIcon size={13} className="shrink-0 text-subtle" />
          ) : (
            item.icon && <span>{item.icon}</span>
          )}
          <span className="truncate" style={item.color ? { color: item.color } : undefined}>
            {item.title || "Без названия"}
          </span>
        </div>
        {preview && <div className="mt-0.5 truncate text-xs text-subtle">{preview}</div>}
        <div className="mt-0.5 truncate text-xs text-subtle">
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
  onSelectDialog,
  isVault = false,
}: {
  spaceId: string;
  folderId: string | null;
  tagId: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  // "Обсудить с ассистентом" (закреплённая строка ниже) открывает не
  // заметку, а диалог — тот же механизм навигации, что уже используют
  // DialogList/ActivityView (переключает viewMode на "assistant" через URL),
  // не отдельное модальное окно поверх редактора (в отличие от
  // NoteAssistantModal.tsx — тот скоуп на одну заметку, живёт внутри неё).
  onSelectDialog: (id: string) => void;
  // Списки в сейфе пока не поддерживаются (см. routers/lists.py) — их
  // пункты хранятся в properties.entries, не в title/content, шифровать
  // их — отдельная, ещё не сделанная работа. Прячем кнопку, а не просто
  // блокируем на сервере — иначе выглядело бы как баг, а не как решение.
  isVault?: boolean;
}) {
  const effectiveFolderId = tagId ? null : folderId;
  // По тегу — кросс-спейсово (тег не привязан к одному спейсу, заметки под
  // ним могут лежать в разных): spaceId здесь остаётся нужен НИЖЕ, для
  // "+ Заметка"/"+ Список" (создание всегда идёт в текущий активный спейс),
  // но не как фильтр списка.
  const effectiveSpaceId = tagId ? undefined : spaceId;
  const { data: items, isLoading } = useItems(effectiveSpaceId, effectiveFolderId, tagId);
  const createItem = useCreateItem();
  const createList = useCreateList();
  const createTable = useCreateTable();
  const createDialog = useCreateDialog();
  const scopedFolderDialogs = useScopedFolderDialogs();
  const [folderDialogPicker, setFolderDialogPicker] = useState<DialogSummary[] | null>(null);
  const assistantRowRef = useRef<HTMLButtonElement>(null);
  // "root" — служебное значение "Без папки" (см. FolderTree.tsx), не
  // настоящая папка: обсуждать с ассистентом "все заметки без папки" не
  // тот же сценарий, что "заметки одной папки на одну тему" — строку не
  // показываем ни для него, ни для "Все заметки" (null), ни в режиме тега.
  const isRealFolder = !!effectiveFolderId && effectiveFolderId !== "root";

  async function openFolderAssistant() {
    if (!isRealFolder || !effectiveFolderId) return;
    const dialogs = await scopedFolderDialogs.mutateAsync(effectiveFolderId);
    if (dialogs.length === 0) {
      const dialog = await createDialog.mutateAsync({ scoped_folder_id: effectiveFolderId });
      onSelectDialog(dialog.id);
    } else {
      setFolderDialogPicker(dialogs);
    }
  }

  async function startNewFolderDialog() {
    if (!isRealFolder || !effectiveFolderId) return;
    setFolderDialogPicker(null);
    const dialog = await createDialog.mutateAsync({ scoped_folder_id: effectiveFolderId });
    onSelectDialog(dialog.id);
  }

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

  async function createNewTable() {
    const targetFolderId = effectiveFolderId === "root" ? null : effectiveFolderId;
    const table = await createTable.mutateAsync({ space_id: spaceId, folder_id: targetFolderId });
    onSelect(table.id);
  }

  const pinned = (items ?? []).filter((i) => i.pinned);
  const rest = (items ?? []).filter((i) => !i.pinned);

  return (
    <div className="flex h-full flex-col">
      {/* На десктопе — обычные кнопки сверху. На телефоне верх экрана до
          них тянуться неудобно (жалоба с телефона), поэтому там вместо
          них плавающие кнопки снизу-справа — чуть выше кнопки «Отзыв»,
          чтобы не перекрывались.
          Реальная жалоба: три текстовые кнопки "+ Заметка/Список/Таблица"
          подряд ломали вёрстку в узкой (особенно после ресайза) панели
          списка. Заметка остаётся основной, текстовой (самое частое
          действие) — Список и Таблица теперь компактные квадратные иконки
          рядом, не растягиваются на всю ширину и не зависят от длины
          перевода слова "Таблица". */}
      <div className="hidden gap-2 border-b p-3 md:flex">
        <div className="flex min-w-0 flex-1">
          <button
            onClick={() => createNote()}
            disabled={createItem.isPending}
            className="flex min-w-0 flex-1 items-center justify-center gap-2 rounded-l bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {createItem.isPending && <Spinner />}
            <span className="truncate">{createItem.isPending ? "Создаём…" : "+ Заметка"}</span>
          </button>
          <NoteTemplateMenu onSelect={createNote} disabled={createItem.isPending} align="top" />
        </div>
        {!isVault && (
          <button
            onClick={createNewList}
            disabled={createList.isPending}
            title="Новый список"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-strong text-primary disabled:opacity-50"
          >
            {createList.isPending ? <Spinner size={16} /> : <ListChecks size={16} />}
          </button>
        )}
        {!isVault && (
          <button
            onClick={createNewTable}
            disabled={createTable.isPending}
            title="Новая таблица"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-strong text-primary disabled:opacity-50"
          >
            {createTable.isPending ? <Spinner size={16} /> : <TableIcon size={16} />}
          </button>
        )}
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto pb-20 md:pb-0">
        {isRealFolder && (
          <li className="border-b bg-brand/10">
            <button
              ref={assistantRowRef}
              onClick={openFolderAssistant}
              disabled={scopedFolderDialogs.isPending || createDialog.isPending}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium text-brand hover:bg-brand/15 disabled:opacity-50"
            >
              {scopedFolderDialogs.isPending || createDialog.isPending ? (
                <Spinner size={14} />
              ) : (
                <MessageSquareText size={14} className="shrink-0" />
              )}
              Обсудить с ассистентом
            </button>
          </li>
        )}
        {isLoading && (
          <li className="flex items-center gap-2 p-3 text-sm text-subtle">
            <Spinner /> Загрузка…
          </li>
        )}
        {!isLoading && (items ?? []).length === 0 && (
          <li className="p-3 text-sm text-subtle">Здесь пока пусто</li>
        )}
        {pinned.length > 0 && (
          <>
            <li className="bg-muted px-3 py-1 text-xs font-medium uppercase tracking-wide text-subtle">
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
        {!isVault && (
          <button
            onClick={createNewTable}
            disabled={createTable.isPending}
            title="Новая таблица"
            className="flex h-11 w-11 items-center justify-center rounded-full bg-surface text-primary shadow-lg ring-1 ring-default disabled:opacity-50"
          >
            {createTable.isPending ? <Spinner size={18} /> : <TableIcon size={18} />}
          </button>
        )}
        {!isVault && (
          <button
            onClick={createNewList}
            disabled={createList.isPending}
            title="Новый список"
            className="flex h-11 w-11 items-center justify-center rounded-full bg-surface text-primary shadow-lg ring-1 ring-default disabled:opacity-50"
          >
            {createList.isPending ? <Spinner size={18} /> : <ListChecks size={18} />}
          </button>
        )}
        <div className="relative">
          <button
            onClick={() => createNote()}
            disabled={createItem.isPending}
            title="Новая заметка"
            className="flex h-14 w-14 items-center justify-center rounded-full bg-accent text-white shadow-lg disabled:opacity-50"
          >
            {createItem.isPending ? <Spinner size={20} /> : <Plus size={24} />}
          </button>
          <div className="absolute -left-1 -top-1">
            <NoteTemplateMenu onSelect={createNote} disabled={createItem.isPending} align="bottom" />
          </div>
        </div>
      </div>
      {folderDialogPicker && (
        <FolderDialogPicker
          anchorRef={assistantRowRef}
          dialogs={folderDialogPicker}
          onPick={(id) => {
            setFolderDialogPicker(null);
            onSelectDialog(id);
          }}
          onNew={startNewFolderDialog}
          onClose={() => setFolderDialogPicker(null)}
          onDeleted={(id) => {
            setFolderDialogPicker((prev) => {
              const next = (prev ?? []).filter((d) => d.id !== id);
              // Последний чат этой папки удалён — не оставляем пустое
              // меню, сразу создаём новый (тот же случай, что и в
              // openFolderAssistant, когда прошлых чатов не было вообще).
              if (next.length === 0) startNewFolderDialog();
              return next.length === 0 ? null : next;
            });
          }}
        />
      )}
    </div>
  );
}
