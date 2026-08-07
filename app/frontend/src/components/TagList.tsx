import { FormEvent, useState } from "react";
import { Pencil, Shuffle, X } from "lucide-react";
import type { Tag } from "../api/types";
import { useCreateTag, useDeleteTag, useMergeTag, useRenameTag, useTags } from "../api/hooks";
import Spinner from "./Spinner";
import PromptDialog from "./PromptDialog";
import ConfirmDialog from "./ConfirmDialog";

export default function TagList({
  selectedTagId,
  onSelect,
}: {
  selectedTagId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const { data: tags } = useTags();
  const createTag = useCreateTag();
  const renameTag = useRenameTag();
  const deleteTag = useDeleteTag();
  const mergeTag = useMergeTag();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<Tag | null>(null);
  const [deleting, setDeleting] = useState<Tag | null>(null);
  const [merging, setMerging] = useState<Tag | null>(null);

  async function submitNew(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await createTag.mutateAsync(name.trim());
    setName("");
    setAdding(false);
  }

  return (
    <div className="mb-4">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Теги</span>
        <button onClick={() => setAdding((v) => !v)} className="text-xs text-slate-400 hover:text-slate-700">
          + новый
        </button>
      </div>
      <ul className="space-y-0.5">
        {(tags ?? []).map((tag) => (
          <li key={tag.id} className="flex items-center justify-between rounded px-2 py-1 text-sm">
            <button
              onClick={() => onSelect(selectedTagId === tag.id ? null : tag.id)}
              className={`flex-1 truncate text-left ${
                selectedTagId === tag.id ? "font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              #{tag.name}
            </button>
            <span className="flex shrink-0 gap-0.5">
              <button
                title="Переименовать"
                onClick={() => setRenaming(tag)}
                className="flex h-6 w-6 items-center justify-center text-slate-400 hover:text-slate-700"
              >
                <Pencil size={12} />
              </button>
              <button
                title="Слить с другим тегом"
                onClick={() => setMerging(tag)}
                className="flex h-6 w-6 items-center justify-center text-slate-400 hover:text-slate-700"
              >
                <Shuffle size={12} />
              </button>
              <button
                title="Удалить"
                onClick={() => setDeleting(tag)}
                className="flex h-6 w-6 items-center justify-center text-slate-400 hover:text-red-600"
              >
                <X size={14} />
              </button>
            </span>
          </li>
        ))}
      </ul>
      {adding && (
        <form onSubmit={submitNew} className="mt-2 flex gap-1">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название тега"
            className="w-full rounded border px-2 py-1 text-sm"
          />
          <button
            type="submit"
            disabled={createTag.isPending}
            className="flex shrink-0 items-center justify-center gap-1 rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-50"
          >
            {createTag.isPending ? <Spinner size={12} /> : "OK"}
          </button>
          <button
            type="button"
            onClick={() => {
              setName("");
              setAdding(false);
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
          title={`Переименовать тег «${renaming.name}»`}
          initialValue={renaming.name}
          onConfirm={(newName) => {
            if (newName !== renaming.name) renameTag.mutate({ id: renaming.id, name: newName });
            setRenaming(null);
          }}
          onCancel={() => setRenaming(null)}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={`Удалить тег «${deleting.name}»?`}
          danger
          onConfirm={() => {
            deleteTag.mutate(deleting.id);
            if (selectedTagId === deleting.id) onSelect(null);
            setDeleting(null);
          }}
          onCancel={() => setDeleting(null)}
        />
      )}

      {merging && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setMerging(null)}
        >
          <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl">
            <div className="mb-2 text-sm font-medium text-slate-900">Слить «{merging.name}» с каким тегом?</div>
            <div className="max-h-64 overflow-y-auto">
              {(tags ?? [])
                .filter((t) => t.id !== merging.id)
                .map((t) => (
                  <button
                    key={t.id}
                    onClick={() => {
                      mergeTag.mutate({ id: merging.id, targetTagId: t.id });
                      setMerging(null);
                    }}
                    className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-slate-100"
                  >
                    #{t.name}
                  </button>
                ))}
              {(tags ?? []).length <= 1 && <div className="px-2 py-1.5 text-sm text-slate-400">Других тегов нет</div>}
            </div>
            <div className="mt-3 flex justify-end">
              <button
                onClick={() => setMerging(null)}
                className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
