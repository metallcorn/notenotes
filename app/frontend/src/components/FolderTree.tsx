import { FormEvent, useEffect, useRef, useState } from "react";
import type { DragEvent, RefObject } from "react";
import { createPortal } from "react-dom";
import { FolderInput, MoreVertical, Pencil, Plus, X } from "lucide-react";
import type { Folder } from "../api/types";
import {
  useCreateFolder,
  useDeleteFolder,
  useFolders,
  useMoveFolderSpace,
  useMoveItemSpace,
  useUpdateFolder,
} from "../api/hooks";
import {
  draggingSomething,
  readDraggedFolder,
  readDraggedItem,
  startFolderDrag,
  type DraggedFolder,
  type DraggedItem,
} from "../lib/dragItem";
import Spinner from "./Spinner";
import PromptDialog from "./PromptDialog";
import ConfirmDialog from "./ConfirmDialog";
import FolderMoveModal from "./FolderMoveModal";

interface NodeProps {
  folder: Folder;
  all: Folder[];
  selectedFolderId: string | null | undefined;
  onSelect: (id: string) => void;
  onAddChild: (parentId: string) => void;
  onRename: (folder: Folder) => void;
  onDelete: (folder: Folder) => void;
  onMove: (folder: Folder) => void;
  dnd: DropHandlers | null;
}

// Что делать с брошенным на строку дерева: target — id папки или null
// («Без папки», то есть корень спейса).
interface DropHandlers {
  onDropItem: (item: DraggedItem, target: string | null) => void;
  onDropFolder: (folder: DraggedFolder, target: string | null) => void;
}

// Подсветка строки под курсором и приём броска. dragleave приходит и при
// переходе на дочерний элемент той же строки — его не считаем уходом.
function useDropTarget(dnd: DropHandlers | null, target: string | null) {
  const [over, setOver] = useState(false);
  if (!dnd) return { over: false, props: {} };
  return {
    over,
    props: {
      onDragOver: (e: DragEvent) => {
        if (!draggingSomething(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (!over) setOver(true);
      },
      onDragLeave: (e: DragEvent) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
      },
      onDrop: (e: DragEvent) => {
        setOver(false);
        const item = readDraggedItem(e);
        if (item) {
          e.preventDefault();
          dnd.onDropItem(item, target);
          return;
        }
        const folder = readDraggedFolder(e);
        if (folder) {
          e.preventDefault();
          dnd.onDropFolder(folder, target);
        }
      },
    },
  };
}

// Реальная жалоба: список спейсов/папок в сайдбаре — единственный
// overflow-y-auto скролл-контейнер (AppShell.tsx:571, там же уже есть
// комментарий про этот класс бага у меню профиля) — абсолютно
// спозиционированное меню папки, когда ниже есть ещё один спейс, обрезалось/
// перекрывалось им: containing block лежит ВНУТРИ скролл-контейнера, тот
// клипует всё, что выходит за его границы. Портал в document.body с
// position:fixed (тот же приём, что уже применён у ExpandedTextPanel в
// RecognizedTextView.tsx и у попапов слэш-команд) решает это раз и навсегда.
function FolderMenu({ folder, triggerRef, onAddChild, onRename, onMove, onDelete, onClose }: {
  folder: Folder;
  triggerRef: RefObject<HTMLButtonElement>;
  onAddChild: (id: string) => void;
  onRename: (folder: Folder) => void;
  onMove: (folder: Folder) => void;
  onDelete: (folder: Folder) => void;
  onClose: () => void;
}) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const width = 176; // w-44
    const margin = 8;
    setPos({
      top: r.bottom + 4,
      left: Math.min(r.right - width, window.innerWidth - width - margin),
    });
  }, [triggerRef]);

  if (!pos) return null;

  return createPortal(
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        style={{ top: pos.top, left: pos.left }}
        className="fixed z-50 w-52 overflow-hidden rounded-2xl border bg-surface py-1 shadow-lg"
      >
        <button
          onClick={() => {
            onAddChild(folder.id);
            onClose();
          }}
          className="flex min-h-10 w-full items-center gap-2.5 px-4 text-left text-sm font-semibold text-secondary hover:bg-muted"
        >
          <Plus size={14} /> Подпапка
        </button>
        <button
          onClick={() => {
            onRename(folder);
            onClose();
          }}
          className="flex min-h-10 w-full items-center gap-2.5 px-4 text-left text-sm font-semibold text-secondary hover:bg-muted"
        >
          <Pencil size={13} /> Переименовать
        </button>
        <button
          onClick={() => {
            onMove(folder);
            onClose();
          }}
          className="flex min-h-10 w-full items-center gap-2.5 px-4 text-left text-sm font-semibold text-secondary hover:bg-muted"
        >
          <FolderInput size={13} /> Перенести в другой спейс
        </button>
        <button
          onClick={() => {
            onDelete(folder);
            onClose();
          }}
          className="flex min-h-10 w-full items-center gap-2.5 px-4 text-left text-sm font-bold text-danger hover:bg-danger-soft"
        >
          <X size={14} /> Удалить
        </button>
      </div>
    </>,
    document.body,
  );
}

function FolderNode({ folder, all, selectedFolderId, onSelect, onAddChild, onRename, onDelete, onMove, dnd }: NodeProps) {
  const children = all.filter((f) => f.parent_id === folder.id);
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drop = useDropTarget(dnd, folder.id);
  return (
    <li>
      <div
        {...drop.props}
        draggable={!!dnd}
        onDragStart={(e) => {
          // Иначе dragstart всплывёт до строки родительской папки, и
          // тащиться будет она.
          e.stopPropagation();
          startFolderDrag(e, { id: folder.id, space_id: folder.space_id });
        }}
        className={`flex min-h-10 items-center justify-between rounded-xl pl-3 pr-0.5 text-sm font-semibold transition-colors ${
          drop.over
            ? "bg-brand/15 ring-1 ring-brand"
            : selectedFolderId === folder.id
              ? "bg-brand-soft text-brand-text"
              : "text-secondary hover:bg-muted"
        }`}
      >
        <button className="min-h-10 flex-1 truncate text-left" onClick={() => onSelect(folder.id)}>
          {folder.name}
        </button>
        {/* Раньше тут было три отдельные кнопки подряд — реальная жалоба:
            на узкой (особенно свежеразвёрнутой, до ресайза) панели
            занимали слишком много места на строку папки. h-8 w-8, не
            group-hover — тот же телефонный отзыв, что и раньше: кнопка
            должна быть физически нажимаема на тачскрине без наведения. */}
        <div className="relative shrink-0">
          <button
            ref={triggerRef}
            title="Действия с папкой"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-subtle hover:bg-muted-hover hover:text-secondary"
          >
            <MoreVertical size={15} />
          </button>
          {menuOpen && (
            <FolderMenu
              folder={folder}
              triggerRef={triggerRef}
              onAddChild={onAddChild}
              onRename={onRename}
              onMove={onMove}
              onDelete={onDelete}
              onClose={() => setMenuOpen(false)}
            />
          )}
        </div>
      </div>
      {children.length > 0 && (
        <ul className="ml-4 border-l pl-1.5">
          {children.map((child) => (
            <FolderNode
              key={child.id}
              folder={child}
              all={all}
              selectedFolderId={selectedFolderId}
              onSelect={onSelect}
              onAddChild={onAddChild}
              onRename={onRename}
              onDelete={onDelete}
              onMove={onMove}
              dnd={dnd}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function FolderTree({
  spaceId,
  selectedFolderId,
  onSelect,
  isVault = false,
}: {
  spaceId: string;
  selectedFolderId: string | null | undefined;
  onSelect: (id: string | null) => void;
  // Сейф не принимает и не отдаёт перетаскиванием: перенос туда — это
  // шифрование в браузере (MigrateToVault), не обычный move.
  isVault?: boolean;
}) {
  const { data: folders } = useFolders(spaceId);
  const createFolder = useCreateFolder(spaceId);
  const updateFolder = useUpdateFolder(spaceId);
  const deleteFolder = useDeleteFolder(spaceId);
  const moveItem = useMoveItemSpace();
  const moveFolderSpace = useMoveFolderSpace();
  const [dropError, setDropError] = useState<string | null>(null);

  useEffect(() => {
    if (!dropError) return;
    const t = setTimeout(() => setDropError(null), 5000);
    return () => clearTimeout(t);
  }, [dropError]);

  const fail = (err: unknown) => setDropError(err instanceof Error ? err.message : "Не удалось перенести");

  const dnd: DropHandlers | null = isVault
    ? null
    : {
        onDropItem: (item, target) => {
          if (item.space_id === spaceId && item.folder_id === target) return;
          moveItem.mutate({ id: item.id, space_id: spaceId, folder_id: target }, { onError: fail });
        },
        onDropFolder: (dragged, target) => {
          if (dragged.space_id !== spaceId) {
            // Между спейсами папка переезжает целиком в корень: так
            // устроен /folders/{id}/move, вложить сразу не выйдет.
            moveFolderSpace.mutate({ id: dragged.id, space_id: spaceId }, { onError: fail });
            return;
          }
          if (dragged.id === target) return;
          // В свою же подпапку — цикл; сервер тоже откажет, но молча
          // пропустить бросок понятнее, чем показать ошибку.
          for (let p = all.find((f) => f.id === target); p; p = all.find((f) => f.id === p!.parent_id)) {
            if (p.id === dragged.id) return;
          }
          if (all.find((f) => f.id === dragged.id)?.parent_id === target) return;
          updateFolder.mutate({ id: dragged.id, parent_id: target }, { onError: fail });
        },
      };
  const rootDrop = useDropTarget(dnd, null);
  const [addingParentId, setAddingParentId] = useState<string | null | undefined>(undefined);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<Folder | null>(null);
  const [deleting, setDeleting] = useState<Folder | null>(null);
  const [moving, setMoving] = useState<Folder | null>(null);

  const all = folders ?? [];
  const roots = all.filter((f) => f.parent_id === null);

  async function submitNew(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    await createFolder.mutateAsync({ name: newName.trim(), parent_id: addingParentId ?? null });
    setNewName("");
    setAddingParentId(undefined);
  }

  return (
    <div className="pb-1 text-primary">
      <ul className="space-y-0.5">
        <li>
          <button
            onClick={() => onSelect(null)}
            className={`min-h-10 w-full rounded-xl px-3 text-left text-sm font-semibold transition-colors ${
              selectedFolderId === null ? "bg-brand-soft text-brand-text" : "text-secondary hover:bg-muted"
            }`}
          >
            Все заметки
          </button>
        </li>
        <li {...rootDrop.props}>
          <button
            onClick={() => onSelect("root")}
            className={`min-h-10 w-full rounded-xl px-3 text-left text-sm font-semibold transition-colors ${
              rootDrop.over
                ? "bg-brand/15 ring-1 ring-brand"
                : selectedFolderId === "root"
                  ? "bg-brand-soft text-brand-text"
                  : "text-secondary hover:bg-muted"
            }`}
          >
            Без папки
          </button>
        </li>
        {roots.map((folder) => (
          <FolderNode
            key={folder.id}
            folder={folder}
            all={all}
            selectedFolderId={selectedFolderId}
            onSelect={onSelect}
            onAddChild={(parentId) => setAddingParentId(parentId)}
            onRename={setRenaming}
            onDelete={setDeleting}
            onMove={setMoving}
            dnd={dnd}
          />
        ))}
      </ul>
      <button
        onClick={() => setAddingParentId(addingParentId === null ? undefined : null)}
        className="mt-0.5 flex min-h-9 items-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-subtle hover:bg-muted hover:text-secondary"
      >
        <Plus size={14} /> Новая папка
      </button>
      {dropError && <p className="mt-1 px-2 text-xs text-danger">{dropError}</p>}

      {addingParentId !== undefined && (
        <form onSubmit={submitNew} className="mt-1 flex gap-1.5 px-1">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Название папки"
            className="h-10 w-full min-w-0 rounded-xl border bg-surface px-3 text-sm"
          />
          <button
            type="submit"
            disabled={createFolder.isPending}
            className="flex h-10 shrink-0 items-center justify-center gap-1 rounded-xl bg-accent px-3 text-xs font-bold text-on-accent disabled:opacity-50"
          >
            {createFolder.isPending ? <Spinner size={12} /> : "OK"}
          </button>
          <button
            type="button"
            onClick={() => {
              setNewName("");
              setAddingParentId(undefined);
            }}
            title="Отменить"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border text-subtle hover:bg-muted-hover"
          >
            <X size={14} />
          </button>
        </form>
      )}

      {renaming && (
        <PromptDialog
          title={`Переименовать папку «${renaming.name}»`}
          initialValue={renaming.name}
          onConfirm={(name) => {
            if (name !== renaming.name) updateFolder.mutate({ id: renaming.id, name });
            setRenaming(null);
          }}
          onCancel={() => setRenaming(null)}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={`Удалить папку «${deleting.name}»? Заметки внутри останутся без папки.`}
          danger
          onConfirm={() => {
            deleteFolder.mutate(deleting.id);
            if (selectedFolderId === deleting.id) onSelect(null);
            setDeleting(null);
          }}
          onCancel={() => setDeleting(null)}
        />
      )}

      {moving && (
        <FolderMoveModal
          folder={moving}
          onClose={() => setMoving(null)}
          onMoved={() => {
            // Папка уехала в другой спейс — в текущем её больше нет,
            // держать выбранной ссылку на несуществующую папку нельзя
            // (тот же приём, что при удалении папки выше).
            if (selectedFolderId === moving.id) onSelect(null);
          }}
        />
      )}
    </div>
  );
}
