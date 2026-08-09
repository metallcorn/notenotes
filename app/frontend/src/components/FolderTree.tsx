import { FormEvent, useState } from "react";
import { Pencil, Plus, X } from "lucide-react";
import type { Folder } from "../api/types";
import { useCreateFolder, useDeleteFolder, useFolders, useUpdateFolder } from "../api/hooks";
import Spinner from "./Spinner";
import PromptDialog from "./PromptDialog";
import ConfirmDialog from "./ConfirmDialog";

interface NodeProps {
  folder: Folder;
  all: Folder[];
  selectedFolderId: string | null | undefined;
  onSelect: (id: string) => void;
  onAddChild: (parentId: string) => void;
  onRename: (folder: Folder) => void;
  onDelete: (folder: Folder) => void;
}

function FolderNode({ folder, all, selectedFolderId, onSelect, onAddChild, onRename, onDelete }: NodeProps) {
  const children = all.filter((f) => f.parent_id === folder.id);
  return (
    <li>
      <div
        className={`flex items-center justify-between rounded px-2 py-1 text-sm ${
          selectedFolderId === folder.id ? "bg-slate-200 font-medium" : "hover:bg-slate-100"
        }`}
      >
        <button className="flex-1 truncate text-left" onClick={() => onSelect(folder.id)}>
          {folder.name}
        </button>
        {/* Не group-hover: на тачскрине :hover не срабатывает вообще —
            кнопки были физически недостижимы на телефоне. h-8 w-8 (было
            h-6 w-6) — тот же телефонный отзыв: 24px физически не попасть
            пальцем, тем более три кнопки подряд. */}
        <span className="flex shrink-0 gap-0.5">
          <button
            title="Подпапка"
            onClick={() => onAddChild(folder.id)}
            className="flex h-8 w-8 items-center justify-center text-slate-400 hover:text-slate-700"
          >
            <Plus size={14} />
          </button>
          <button
            title="Переименовать"
            onClick={() => onRename(folder)}
            className="flex h-8 w-8 items-center justify-center text-slate-400 hover:text-slate-700"
          >
            <Pencil size={13} />
          </button>
          <button
            title="Удалить"
            onClick={() => onDelete(folder)}
            className="flex h-8 w-8 items-center justify-center text-slate-400 hover:text-red-600"
          >
            <X size={15} />
          </button>
        </span>
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
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Папки</span>
        <button
          onClick={() => setAddingParentId(addingParentId === null ? undefined : null)}
          className="text-xs text-slate-400 hover:text-slate-700"
        >
          + новая
        </button>
      </div>

      <ul className="space-y-0.5">
        <li>
          <button
            onClick={() => onSelect(null)}
            className={`w-full rounded px-2 py-1 text-left text-sm ${
              selectedFolderId === null ? "bg-slate-200 font-medium" : "hover:bg-slate-100"
            }`}
          >
            Все заметки
          </button>
        </li>
        <li>
          <button
            onClick={() => onSelect("root")}
            className={`w-full rounded px-2 py-1 text-left text-sm ${
              selectedFolderId === "root" ? "bg-slate-200 font-medium" : "hover:bg-slate-100"
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
            className="flex shrink-0 items-center justify-center gap-1 rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-50"
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
            className="flex shrink-0 items-center justify-center rounded border px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
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
    </div>
  );
}
