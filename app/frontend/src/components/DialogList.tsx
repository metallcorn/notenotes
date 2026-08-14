import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useCreateDialog, useDeleteItem, useDialogs } from "../api/hooks";
import type { DialogSummary } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

export default function DialogList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const { data: dialogs, isLoading, isError, refetch } = useDialogs();
  const createDialog = useCreateDialog();
  const deleteItem = useDeleteItem(undefined);
  const qc = useQueryClient();
  const [deleting, setDeleting] = useState<DialogSummary | null>(null);

  async function handleCreate() {
    const dialog = await createDialog.mutateAsync({});
    onSelect(dialog.id);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <button
          onClick={handleCreate}
          disabled={createDialog.isPending}
          className="flex w-full items-center justify-center gap-1.5 rounded bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {createDialog.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
          Новый диалог
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {isLoading && <div className="p-3 text-sm text-slate-400">Загрузка…</div>}
        {/* isError отдельно от "диалогов правда нет" — раньше сбой сети
            (например, на телефоне при слабом сигнале) выглядел неотличимо
            от пустого списка: dialogs просто оставался undefined, и текст
            "пока нет диалогов" показывался как ни в чём не бывало, хотя
            диалоги реально есть на сервере, просто не подгрузились
            (реальная жалоба: "не вижу чатов ассистента", хотя они были). */}
        {isError && (
          <div className="p-3 text-sm text-slate-500">
            Не удалось загрузить диалоги.{" "}
            <button onClick={() => refetch()} className="text-slate-900 underline hover:no-underline">
              Повторить
            </button>
          </div>
        )}
        {!isLoading && !isError && (dialogs ?? []).length === 0 && (
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
            qc.invalidateQueries({ queryKey: ["dialogs"] });
            if (selectedId === deleting.id) onSelect(null);
            setDeleting(null);
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
