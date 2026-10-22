import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { createPortal } from "react-dom";
import { Archive, ChevronDown, FileText, ListChecks, MessageSquareText, Pin, Plus, Table as TableIcon, Trash2 } from "lucide-react";
import {
  useArchiveItem,
  useCreateDialog,
  useCreateItem,
  useCreateList,
  useCreateTable,
  useDeleteItem,
  useItems,
  useScopedFolderDialogs,
  useUpdateItem,
} from "../api/hooks";
import type { DialogSummary, Item } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";
import SwipeRow from "./SwipeRow";
import { ListSkeleton } from "./Skeleton";
import { startItemDrag } from "../lib/dragItem";
import { NOTE_TEMPLATES, type NoteTemplate } from "../lib/noteTemplates";
import { formatRelativeDay } from "../lib/format";
import { dateLocale, t } from "../i18n";

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
        className="fixed z-50 max-h-72 w-64 overflow-y-auto rounded-2xl border bg-surface py-1.5 shadow-lg"
      >
        <button
          onClick={onNew}
          className="flex min-h-10 w-full items-center gap-2.5 px-4 text-left text-sm font-bold text-brand-text hover:bg-brand-soft"
        >
          <Plus size={14} /> Новый диалог
        </button>
        <div className="my-1 border-t" />
        {dialogs.map((d) => (
          <div key={d.id} className="flex items-center gap-1 hover:bg-muted-hover">
            <button onClick={() => onPick(d.id)} className="min-w-0 flex-1 px-3 py-1.5 text-left text-sm text-secondary">
              <div className="truncate">{d.preview || d.title}</div>
              <div className="text-xs text-subtle">{new Date(d.updated_at).toLocaleString(dateLocale)}</div>
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
            ? "flex h-full items-center justify-center border-l border-on-accent/20 bg-accent px-2.5 text-on-accent disabled:opacity-50"
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
            <div style={pos} className="fixed z-50 w-48 rounded-2xl border bg-surface py-1.5 shadow-lg">
              {NOTE_TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  onClick={() => {
                    setOpen(false);
                    onSelect(t);
                  }}
                  className="block min-h-10 w-full px-4 py-2 text-left text-sm font-semibold text-secondary hover:bg-muted"
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

export function listCounts(content: string): { done: number; total: number } {
  const lines = content.split("\n").filter(Boolean);
  return { done: lines.filter((l) => l.startsWith("[x]")).length, total: lines.length };
}

function NoteRow({
  item,
  selected,
  onSelect,
  draggable,
}: {
  item: Item;
  selected: boolean;
  onSelect: (id: string) => void;
  draggable: boolean;
}) {
  const isList = item.material_type === "list";
  const isTable = item.material_type === "table";
  const preview = isList ? "" : previewText(item.content);
  const counts = isList ? listCounts(item.content) : null;
  const when = formatRelativeDay(item.updated_at, dateLocale);
  const updateItem = useUpdateItem();
  const archiveItem = useArchiveItem(item.space_id);
  return (
    // row-fade-in — на корне строки. Срабатывает только на новых узлах:
    // при стабильном key={item.id} React переиспользует уже отрисованные
    // строки, и обновление списка не переигрывает анимацию на всех
    // (см. комментарий к .row-fade-in в index.css).
    <li className="row-fade-in px-3 pb-2">
      {/* Карточка (макет «Заметки в папке», 21.10). Тянется мышкой на
          папку в сайдбаре (lib/dragItem.ts). Из сейфа нельзя: туда и
          оттуда перенос идёт через шифрование, не через обычный move.
          Пальцем — свайп влево: закрепить / в архив (замечание 22.10). */}
      <SwipeRow
        actions={[
          { label: item.pinned ? "Открепить" : "Закрепить", tone: "lime", icon: <Pin size={16} />, onClick: () => updateItem.mutate({ id: item.id, pinned: !item.pinned }) },
          { label: "В архив", tone: "dark", icon: <Archive size={16} />, onClick: () => archiveItem.mutate(item.id) },
        ]}
      >
      <button
        onClick={() => onSelect(item.id)}
        draggable={draggable}
        onDragStart={(e) =>
          startItemDrag(e, { id: item.id, space_id: item.space_id, folder_id: item.folder_id ?? null })
        }
        title={new Date(item.updated_at).toLocaleString(dateLocale)}
        className={`flex w-full gap-3 rounded-2xl bg-surface p-3.5 text-left shadow-card transition-[box-shadow,transform] active:scale-[0.99] ${
          selected ? "ring-2 ring-brand" : item.pinned ? "ring-2 ring-lime" : "hover:shadow-float"
        }`}
      >
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-muted text-[22px] leading-none">
          {isList ? (
            <ListChecks size={20} className="text-primary" />
          ) : isTable ? (
            <TableIcon size={20} className="text-primary" />
          ) : (
            item.icon || <FileText size={20} className="text-subtle" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className="truncate text-[15px] font-extrabold leading-tight text-primary"
              style={item.color ? { color: item.color } : undefined}
            >
              {item.title || "Без названия"}
            </span>
            {item.pinned && <Pin size={13} className="shrink-0 text-primary" aria-label="Закреплено" />}
          </div>
          {preview && <div className="mt-0.5 truncate text-[13px] leading-snug text-subtle">{preview}</div>}
          {counts && counts.total > 0 && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-brand transition-[width]"
                style={{ width: `${Math.round((counts.done / counts.total) * 100)}%` }}
              />
            </div>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs font-bold text-nav-muted">
            {counts && <span>{counts.total === 0 ? "Пусто" : `${counts.done} из ${counts.total}`} · </span>}
            <span>{when}</span>
            {item.tags.slice(0, 3).map((t) => (
              <span key={t.id} className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-bold text-brand-text">
                #{t.name}
              </span>
            ))}
          </div>
        </div>
      </button>
      </SwipeRow>
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
      {/* На десктопе — обычные кнопки сверху. На телефоне создание идёт
          через «+» нижней панели (BottomNav → CreateSheet): раньше тут были
          плавающие кнопки снизу-справа, они перекрывали бы панель.
          Реальная жалоба: три текстовые кнопки "+ Заметка/Список/Таблица"
          подряд ломали вёрстку в узкой (особенно после ресайза) панели
          списка. Заметка остаётся основной, текстовой (самое частое
          действие) — Список и Таблица теперь компактные квадратные иконки
          рядом, не растягиваются на всю ширину и не зависят от длины
          перевода слова "Таблица". */}
      <div className="hidden gap-2 p-3 md:flex">
        <div className="flex min-w-0 flex-1 overflow-hidden rounded-xl">
          <button
            onClick={() => createNote()}
            disabled={createItem.isPending}
            className="flex h-10 min-w-0 flex-1 items-center justify-center gap-2 bg-accent px-3 text-sm font-bold text-on-accent disabled:opacity-50"
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
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface text-primary shadow-card hover:bg-muted disabled:opacity-50"
          >
            {createList.isPending ? <Spinner size={16} /> : <ListChecks size={16} />}
          </button>
        )}
        {!isVault && (
          <button
            onClick={createNewTable}
            disabled={createTable.isPending}
            title="Новая таблица"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface text-primary shadow-card hover:bg-muted disabled:opacity-50"
          >
            {createTable.isPending ? <Spinner size={16} /> : <TableIcon size={16} />}
          </button>
        )}
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto pt-1">
        {isRealFolder && (
          <li className="px-3 pb-2">
            <button
              ref={assistantRowRef}
              onClick={openFolderAssistant}
              disabled={scopedFolderDialogs.isPending || createDialog.isPending}
              className="flex min-h-11 w-full items-center gap-2.5 rounded-2xl bg-brand-soft px-4 text-left text-sm font-bold text-brand-text hover:bg-brand/20 disabled:opacity-50"
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
          // Скелет вместо спиннера: он занимает площадь будущих строк, и
          // экран не прыгает в момент подстановки данных.
          <li>
            <ListSkeleton rows={7} withIcon={false} />
          </li>
        )}
        {!isLoading && (items ?? []).length === 0 && (
          <li className="px-4 py-6 text-center text-sm font-semibold text-subtle">Здесь пока пусто</li>
        )}
        {pinned.length > 0 && (
          <>
            <li className="px-4 pb-1.5 pt-1 text-[11px] font-extrabold uppercase tracking-wider text-subtle">
              {t("list.pinned")}
            </li>
            {pinned.map((item) => (
              <NoteRow key={item.id} item={item} selected={selectedId === item.id} onSelect={onSelect} draggable={!isVault} />
            ))}
          </>
        )}
        {pinned.length > 0 && rest.length > 0 && (
          <li className="px-4 pb-1.5 pt-2 text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("list.recent")}</li>
        )}
        {rest.map((item) => (
          <NoteRow key={item.id} item={item} selected={selectedId === item.id} onSelect={onSelect} draggable={!isVault} />
        ))}
      </ul>
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
