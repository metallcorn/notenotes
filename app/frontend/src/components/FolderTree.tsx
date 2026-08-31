import { FormEvent, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { createPortal } from "react-dom";
import { FolderInput, MoreVertical, Pencil, Plus, X } from "lucide-react";
import type { Folder } from "../api/types";
import { useCreateFolder, useDeleteFolder, useFolders, useUpdateFolder } from "../api/hooks";
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
        className="fixed z-50 w-44 rounded border bg-surface py-1 shadow-lg"
      >
        <button
          onClick={() => {
            onAddChild(folder.id);
            onClose();
          }}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
        >
          <Plus size={14} /> Подпапка
        </button>
        <button
          onClick={() => {
            onRename(folder);
            onClose();
          }}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
        >
          <Pencil size={13} /> Переименовать
        </button>
        <button
          onClick={() => {
            onMove(folder);
            onClose();
          }}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
        >
          <FolderInput size={13} /> Перенести в другой спейс
        </button>
        <button
          onClick={() => {
            onDelete(folder);
            onClose();
          }}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-danger hover:bg-danger/10"
        >
          <X size={14} /> Удалить
        </button>
      </div>
    </>,
    document.body,
  );
}

function FolderNode({ folder, all, selectedFolderId, onSelect, onAddChild, onRename, onDelete, onMove }: NodeProps) {
  const children = all.filter((f) => f.parent_id === folder.id);
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <li>
      <div
        className={`flex items-center justify-between rounded px-2 py-1 text-sm ${
          selectedFolderId === folder.id ? "bg-muted-active font-medium" : "hover:bg-muted-hover"
        }`}
      >
        <button className="flex-1 truncate text-left" onClick={() => onSelect(folder.id)}>
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
            className="flex h-8 w-8 items-center justify-center text-subtle hover:text-secondary"
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
        <ul className="ml-3 border-l pl-2">
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
}: {
  spaceId: string;
  selectedFolderId: string | null | undefined;
  onSelect: (id: string | null) => void;
}) {
  const { data: folders } = useFolders(spaceId);
  const createFolder = useCreateFolder(spaceId);
  const updateFolder = useUpdateFolder(spaceId);
  const deleteFolder = useDeleteFolder(spaceId);
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
    <div className="mb-4">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-subtle">Папки</span>
        <button
          onClick={() => setAddingParentId(addingParentId === null ? undefined : null)}
          className="text-xs text-subtle hover:text-secondary"
        >
          + новая
        </button>
      </div>

      <ul className="space-y-0.5">
        <li>
          <button
            onClick={() => onSelect(null)}
            className={`w-full rounded px-2 py-1 text-left text-sm ${
              selectedFolderId === null ? "bg-muted-active font-medium" : "hover:bg-muted-hover"
            }`}
          >
            Все заметки
          </button>
        </li>
        <li>
          <button
            onClick={() => onSelect("root")}
            className={`w-full rounded px-2 py-1 text-left text-sm ${
              selectedFolderId === "root" ? "bg-muted-active font-medium" : "hover:bg-muted-hover"
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
          />
        ))}
      </ul>

      {addingParentId !== undefined && (
        <form onSubmit={submitNew} className="mt-2 flex gap-1">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Название папки"
            className="w-full rounded border px-2 py-1 text-sm"
          />
          <button
            type="submit"
            disabled={createFolder.isPending}
            className="flex shrink-0 items-center justify-center gap-1 rounded bg-accent px-2 py-1 text-xs text-white disabled:opacity-50"
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
            className="flex shrink-0 items-center justify-center rounded border px-2 py-1 text-xs text-subtle hover:bg-muted-hover"
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
