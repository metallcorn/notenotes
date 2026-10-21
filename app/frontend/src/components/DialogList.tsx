import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useCreateDialog, useDeleteItem, useDialogs } from "../api/hooks";
import type { DialogSummary } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";
import { ListSkeleton } from "./Skeleton";

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
      <div className="p-3">
        <button
          onClick={handleCreate}
          disabled={createDialog.isPending}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-accent px-3 text-[15px] font-extrabold text-on-accent hover:bg-accent/90 disabled:opacity-50"
        >
          {createDialog.isPending ? <Spinner size={14} /> : <Plus size={18} strokeWidth={2.6} />}
          Новый диалог
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3">
        {isLoading && <ListSkeleton rows={5} />}
        {/* isError отдельно от "диалогов правда нет" — раньше сбой сети
            (например, на телефоне при слабом сигнале) выглядел неотличимо
            от пустого списка: dialogs просто оставался undefined, и текст
            "пока нет диалогов" показывался как ни в чём не бывало, хотя
            диалоги реально есть на сервере, просто не подгрузились
            (реальная жалоба: "не вижу чатов ассистента", хотя они были). */}
        {isError && (
          <div className="p-3 text-sm text-subtle">
            Не удалось загрузить диалоги.{" "}
            <button onClick={() => refetch()} className="text-primary underline hover:no-underline">
              Повторить
            </button>
          </div>
        )}
        {!isLoading && !isError && (dialogs ?? []).length === 0 && (
          <div className="p-3 text-sm text-subtle">Пока нет диалогов с ассистентом</div>
        )}
        {(dialogs ?? []).map((d) => (
          <div
            key={d.id}
            className={`row-fade-in mb-2 flex items-center rounded-2xl bg-surface shadow-card ${
              selectedId === d.id ? "ring-2 ring-brand" : "hover:shadow-float"
            }`}
          >
            <button
              onClick={() => onSelect(d.id)}
              className="min-w-0 flex-1 px-4 py-3 text-left"
            >
              <div className="truncate text-[15px] font-extrabold text-primary">{d.title || "Новый диалог"}</div>
              {d.preview && <div className="mt-0.5 truncate text-[13px] text-subtle">{d.preview}</div>}
            </button>
            <button
              onClick={() => setDeleting(d)}
              title="Удалить диалог"
              className="mr-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-muted hover:text-danger"
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
