import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useCreateDialog, useDeleteItem, useDialogs } from "../api/hooks";
import type { DialogSummary } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

export default function DialogList({
  spaceId,
  selectedId,
  onSelect,
}: {
  spaceId: string | undefined;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const { data: dialogs, isLoading } = useDialogs(spaceId);
  const createDialog = useCreateDialog(spaceId);
  const deleteItem = useDeleteItem(spaceId);
  const qc = useQueryClient();
  const [deleting, setDeleting] = useState<DialogSummary | null>(null);

  async function handleCreate() {
    const dialog = await createDialog.mutateAsync();
    onSelect(dialog.id);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <button
          onClick={handleCreate}
          disabled={createDialog.isPending || !spaceId}
          className="flex w-full items-center justify-center gap-1.5 rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {createDialog.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
          Новый диалог
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {isLoading && <div className="p-3 text-sm text-slate-400">Загрузка…</div>}
        {!isLoading && (dialogs ?? []).length === 0 && (
          <div className="p-3 text-sm text-slate-400">Пока нет диалогов с ассистентом</div>
        )}
        {(dialogs ?? []).map((d) => (
          <div
            key={d.id}
            className={`flex items-center border-b ${
              selectedId === d.id ? "bg-slate-100" : "hover:bg-slate-50"
            }`}
          >
            <button
              onClick={() => onSelect(d.id)}
              className={`min-w-0 flex-1 truncate px-3 py-2.5 text-left text-sm ${
                selectedId === d.id ? "font-medium text-slate-900" : "text-slate-600"
              }`}
            >
              {d.title || "Новый диалог"}
            </button>
            <button
              onClick={() => setDeleting(d)}
              title="Удалить диалог"
              className="mr-2 flex h-7 w-7 shrink-0 items-center justify-center text-slate-300 hover:text-red-600"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      {deleting && (
        <ConfirmDialog
          title={`Удалить диалог «${deleting.title || "Новый диалог"}»? Он переместится в корзину.`}
          danger
          onConfirm={async () => {
            await deleteItem.mutateAsync(deleting.id);
            qc.invalidateQueries({ queryKey: ["dialogs", spaceId] });
            if (selectedId === deleting.id) onSelect(null);
            setDeleting(null);
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
