import { FormEvent, Suspense, lazy, useState } from "react";
import type { Folder } from "../api/types";
import { useCreateFolder } from "../api/hooks";
import Spinner from "./Spinner";
import { t } from "../i18n";

const EmojiPickerPopover = lazy(() => import("./EmojiPickerPopover"));

// «Новая папка» (макет «Действия с папкой», 21.10): плитка со значком
// слева, название справа. Значок — тот же пикер, что у заметки.
export default function NewFolderDialog({
  spaceId,
  parent,
  onClose,
  onCreated,
}: {
  spaceId: string;
  parent: Folder | null;
  onClose: () => void;
  onCreated?: (folder: Folder) => void;
}) {
  const createFolder = useCreateFolder(spaceId);
  const [name, setName] = useState("");
  const [icon, setIcon] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || createFolder.isPending) return;
    const folder = await createFolder.mutateAsync({ name: trimmed, parent_id: parent?.id ?? null, icon });
    onCreated?.(folder);
    onClose();
  }

  return (
    <div
      className="modal-in fixed inset-0 z-[60] flex items-start justify-center bg-black/45 p-3 pt-16 sm:items-center"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={parent ? t("folders.newIn", { name: parent.name }) : t("folders.newTop")}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-sm rounded-3xl bg-surface p-5 shadow-xl"
      >
        <div className="text-[13px] font-extrabold uppercase tracking-wider text-subtle">
          {parent ? t("folders.newIn", { name: parent.name }) : t("folders.newTop")}
        </div>
        <div className="mt-3 flex gap-2.5">
          <div className="relative shrink-0">
            <button
              type="button"
              aria-label={t("folders.pickIcon")}
              onClick={() => setPickerOpen((v) => !v)}
              className="flex h-[52px] w-[52px] items-center justify-center rounded-2xl border-[1.5px] border-dashed border-strong bg-muted text-[22px] leading-none"
            >
              {icon ?? "📁"}
            </button>
            {pickerOpen && (
              <Suspense fallback={null}>
                <EmojiPickerPopover
                  onSelect={(emoji) => setIcon(emoji)}
                  onClose={() => setPickerOpen(false)}
                />
              </Suspense>
            )}
          </div>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("folders.name")}
            aria-label={t("folders.name")}
            className="h-[52px] min-w-0 flex-1 rounded-2xl border-2 border-brand bg-surface px-3.5 text-[17px] font-bold text-primary outline-none placeholder:font-semibold placeholder:text-subtle"
          />
        </div>
        <div className="mt-3.5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-11 rounded-2xl bg-muted px-4 text-[15px] font-bold text-primary hover:bg-muted-hover"
          >
            {t("common.cancel")}
          </button>
          <button
            type="submit"
            disabled={!name.trim() || createFolder.isPending}
            className="flex h-11 items-center gap-2 rounded-2xl bg-accent px-5 text-[15px] font-extrabold text-on-accent disabled:opacity-50"
          >
            {createFolder.isPending && <Spinner size={14} />}
            {t("folders.create")}
          </button>
        </div>
      </form>
    </div>
  );
}
