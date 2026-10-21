import { useEffect, useState } from "react";
import { CalendarDays, FileText, Lightbulb, ListChecks, Sparkles, Table as TableIcon, Users } from "lucide-react";
import { useCreateDialog, useCreateItem, useCreateList, useCreateTable, useFolders } from "../api/hooks";
import type { Space } from "../api/types";
import { NOTE_TEMPLATES, type NoteTemplate } from "../lib/noteTemplates";
import Spinner from "./Spinner";
import { t } from "../i18n";

// Шторка «Создать» с кнопки «+» в нижней панели (редизайн 21.10, макет
// «Кнопка +»). Создаёт в текущем спейсе и папке — те же мутации, что
// кнопки в шапке списка (NoteList), только собраны в одном месте и
// доступны с любого экрана, а не только из списка заметок.
export default function CreateSheet({
  space,
  folderId,
  onCreated,
  onDialog,
  onClose,
}: {
  space: Space | undefined;
  // "root" — служебное «Без папки» из FolderTree, null — «Все заметки».
  folderId: string | null;
  onCreated: (itemId: string) => void;
  onDialog: (dialogId: string) => void;
  onClose: () => void;
}) {
  const createItem = useCreateItem();
  const createList = useCreateList();
  const createTable = useCreateTable();
  const createDialog = useCreateDialog();
  const { data: folders } = useFolders(space?.id);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const targetFolderId = folderId === "root" ? null : folderId;
  const folderName = targetFolderId ? folders?.find((f) => f.id === targetFolderId)?.name : undefined;

  async function run(kind: string, action: () => Promise<string>, done: (id: string) => void) {
    if (busy || !space) return;
    setBusy(kind);
    try {
      const id = await action();
      onClose();
      done(id);
    } finally {
      setBusy(null);
    }
  }

  const note = (template?: NoteTemplate) =>
    run(
      template ? `tpl-${template.id}` : "note",
      async () =>
        (
          await createItem.mutateAsync({
            space_id: space!.id,
            folder_id: targetFolderId,
            title: template?.title ?? "",
            content: template?.content ?? "",
          })
        ).id,
      onCreated,
    );
  const list = () =>
    run("list", async () => (await createList.mutateAsync({ space_id: space!.id, folder_id: targetFolderId })).id, onCreated);
  const table = () =>
    run("table", async () => (await createTable.mutateAsync({ space_id: space!.id, folder_id: targetFolderId })).id, onCreated);
  const ask = () => run("ask", async () => (await createDialog.mutateAsync({})).id, onDialog);

  const tile = (kind: string, label: string, title: string, Icon: typeof FileText, onClick: () => void, hidden = false) =>
    hidden ? null : (
      <button
        type="button"
        onClick={onClick}
        disabled={!!busy || !space}
        title={title}
        className="flex h-[88px] flex-col items-center justify-center gap-2 rounded-2xl bg-muted text-sm font-bold text-primary transition-colors hover:bg-muted-hover active:bg-muted-active disabled:opacity-50"
      >
        {busy === kind ? <Spinner size={22} /> : <Icon size={22} strokeWidth={2.2} />}
        <span className="max-w-full truncate px-1">{label}</span>
      </button>
    );

  const templateIcon: Record<string, typeof FileText> = { meeting: Users, diary: CalendarDays, idea: Lightbulb };

  return (
    <div
      className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("create.title")}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="sheet-in w-full max-w-md rounded-t-3xl bg-surface px-4 pb-[max(20px,var(--safe-bottom))] pt-2.5 shadow-xl sm:rounded-3xl sm:pb-5"
      >
        <div className="mx-auto mb-3 h-[5px] w-10 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
        <div className="flex items-baseline justify-between px-1">
          <h2 className="text-2xl font-extrabold tracking-tight text-primary">{t("create.title")}</h2>
          {space && (
            <div className="truncate text-xs font-semibold text-subtle">
              {t("create.where")}: {space.name}
              {folderName ? ` › ${folderName}` : ""}
            </div>
          )}
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          {tile("note", t("create.note"), "Новая заметка", FileText, () => note())}
          {tile("list", t("create.list"), "Новый список", ListChecks, list, !!space?.is_vault)}
          {tile("table", t("create.table"), "Новая таблица", TableIcon, table, !!space?.is_vault)}
        </div>
        <button
          type="button"
          onClick={ask}
          disabled={!!busy}
          className="mt-2 flex h-14 w-full items-center gap-3 rounded-2xl bg-brand-soft px-4 text-left text-sm font-bold text-brand-text transition-colors hover:bg-brand/20 disabled:opacity-50"
        >
          {busy === "ask" ? <Spinner size={20} /> : <Sparkles size={20} strokeWidth={2.2} />}
          {t("create.ask")}
        </button>

        <div className="mt-4 px-1 text-xs font-extrabold uppercase tracking-wider text-subtle">{t("create.templates")}</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {NOTE_TEMPLATES.filter((tpl) => tpl.id !== "blank").map((tpl) => {
            const Icon = templateIcon[tpl.id] ?? FileText;
            return (
              <button
                key={tpl.id}
                type="button"
                onClick={() => note(tpl)}
                disabled={!!busy || !space}
                className="flex h-10 items-center gap-2 rounded-full border border-default bg-surface px-4 text-sm font-semibold text-primary transition-colors hover:bg-muted disabled:opacity-50"
              >
                {busy === `tpl-${tpl.id}` ? <Spinner size={16} /> : <Icon size={16} />}
                {tpl.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
