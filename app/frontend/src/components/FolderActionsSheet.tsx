import { Suspense, lazy, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, FolderPlus, Pencil, Trash2 } from "lucide-react";
import type { Folder } from "../api/types";
import { useDeleteFolder, useUpdateFolder } from "../api/hooks";
import FolderMoveModal from "./FolderMoveModal";
import NewFolderDialog from "./NewFolderDialog";
import PromptDialog from "./PromptDialog";
import { t, tn } from "../i18n";

const EmojiPickerPopover = lazy(() => import("./EmojiPickerPopover"));

// Шторка «Действия с папкой» (макет 21.10): значок + название + счётчики,
// четыре плитки, удаление подтверждается прямо здесь, красной карточкой,
// с явным «куда денутся заметки».
export default function FolderActionsSheet({
  folder,
  notesCount,
  subfoldersCount,
  onClose,
  onDeleted,
}: {
  folder: Folder;
  notesCount: number;
  subfoldersCount: number;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const updateFolder = useUpdateFolder(folder.space_id);
  const deleteFolder = useDeleteFolder(folder.space_id);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [moving, setMoving] = useState(false);
  const [creatingSub, setCreatingSub] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tile = (label: string, Icon: typeof Pencil, onClick: () => void, danger = false) => (
    <button
      type="button"
      onClick={onClick}
      className={`flex h-[76px] flex-col items-center justify-center gap-1.5 rounded-2xl text-xs font-bold transition-colors ${
        danger ? "bg-danger-soft text-danger" : "bg-muted text-primary hover:bg-muted-hover"
      }`}
    >
      <Icon size={20} strokeWidth={2.2} />
      {label}
    </button>
  );

  return createPortal(
    <>
      <div
        className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
        onClick={onClose}
        role="dialog"
        aria-modal="true"
        aria-label={t("folders.actions")}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className="sheet-in w-full max-w-md rounded-t-3xl bg-surface px-3 pb-[max(20px,var(--safe-bottom))] pt-2.5 shadow-xl sm:rounded-3xl sm:pb-5"
        >
          <div className="mx-auto mb-3 h-[5px] w-10 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
          <div className="flex items-center gap-3 px-2 pb-3">
            <div className="relative shrink-0">
              <button
                type="button"
                aria-label={t("folders.pickIcon")}
                onClick={() => setPickerOpen((v) => !v)}
                className="flex h-11 w-11 items-center justify-center rounded-2xl bg-muted text-xl leading-none"
              >
                {folder.icon ?? "📁"}
              </button>
              {pickerOpen && (
                <Suspense fallback={null}>
                  <EmojiPickerPopover
                    onSelect={(emoji) => updateFolder.mutate({ id: folder.id, icon: emoji })}
                    onClose={() => setPickerOpen(false)}
                  />
                </Suspense>
              )}
            </div>
            <div className="min-w-0">
              <div className="truncate text-lg font-extrabold text-primary">{folder.name}</div>
              <div className="text-[13px] font-semibold text-subtle">
                {tn("count.notes", notesCount)}
                {subfoldersCount > 0 ? ` · ${tn("count.subfolders", subfoldersCount)}` : ""}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2 px-1">
            {tile(t("folders.sub"), FolderPlus, () => setCreatingSub(true))}
            {tile(t("folders.rename"), Pencil, () => setRenaming(true))}
            {tile(t("folders.move"), ArrowRight, () => setMoving(true))}
            {tile(t("folders.delete"), Trash2, () => setConfirmingDelete(true), true)}
          </div>
          {confirmingDelete && (
            <div className="mx-1 mt-3 rounded-2xl bg-danger-soft p-3.5 text-danger">
              <div className="text-[15px] font-extrabold">{t("folders.deleteQ", { name: folder.name })}</div>
              <div className="mt-1 text-[13px] font-semibold leading-snug">
                {t("folders.deleteHint", { n: tn("count.notes", notesCount) })}
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(false)}
                  className="h-11 flex-1 rounded-2xl bg-surface text-sm font-bold text-primary"
                >
                  {t("folders.keep")}
                </button>
                <button
                  type="button"
                  disabled={deleteFolder.isPending}
                  onClick={() => {
                    deleteFolder.mutate(folder.id, {
                      onSuccess: () => {
                        onDeleted();
                        onClose();
                      },
                    });
                  }}
                  className="h-11 flex-1 rounded-2xl bg-danger text-sm font-extrabold text-white disabled:opacity-50"
                >
                  {t("folders.deleteConfirm")}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {renaming && (
        <PromptDialog
          title={`Переименовать папку «${folder.name}»`}
          initialValue={folder.name}
          onConfirm={(name) => {
            if (name !== folder.name) updateFolder.mutate({ id: folder.id, name });
            setRenaming(false);
            onClose();
          }}
          onCancel={() => setRenaming(false)}
        />
      )}
      {moving && (
        <FolderMoveModal
          folder={folder}
          onClose={() => {
            setMoving(false);
            onClose();
          }}
          onMoved={onDeleted}
        />
      )}
      {creatingSub && (
        <NewFolderDialog
          spaceId={folder.space_id}
          parent={folder}
          onClose={() => {
            setCreatingSub(false);
            onClose();
          }}
        />
      )}
    </>,
    document.body,
  );
}
