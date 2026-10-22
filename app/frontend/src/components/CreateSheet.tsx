import { useEffect, useState } from "react";
import {
  AlarmClock,
  Camera,
  CalendarDays,
  ChevronDown,
  FileText,
  FileUp,
  Lightbulb,
  Link as LinkIcon,
  ListChecks,
  Mic,
  Sparkles,
  Table as TableIcon,
  Users,
} from "lucide-react";
import { useCreateDialog, useCreateItem, useCreateList, useCreateReminder, useCreateTable, useFolders } from "../api/hooks";
import type { Space } from "../api/types";
import { NOTE_TEMPLATES, type NoteTemplate } from "../lib/noteTemplates";
import { setPendingNoteAction, type PendingNoteAction } from "../lib/pendingNoteAction";
import PromptDialog from "./PromptDialog";
import ReminderModal from "./ReminderModal";
import Spinner from "./Spinner";
import { t } from "../i18n";

// Шторка «Создать» с кнопки «+» в нижней панели (редизайн 21.10, макет
// «Кнопка +»): девять плиток — заметка, список, таблица, голосом, скан/фото,
// файл, напоминание, ссылка, попросить ассистента — и шаблоны. Создаёт в
// выбранном спейсе и папке: пилюля «в Спейс › Папка» раскрывает выбор папки.
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
  const createReminder = useCreateReminder();
  const { data: folders } = useFolders(space?.id);
  const [busy, setBusy] = useState<string | null>(null);
  const [targetFolderId, setTargetFolderId] = useState<string | null>(folderId === "root" ? null : folderId);
  const [folderPickerOpen, setFolderPickerOpen] = useState(false);
  const [linkPrompt, setLinkPrompt] = useState(false);
  const [reminderOpen, setReminderOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

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

  const newNote = async (title = "", content = "") =>
    (await createItem.mutateAsync({ space_id: space!.id, folder_id: targetFolderId, title, content })).id;

  const note = (template?: NoteTemplate) =>
    run(template ? `tpl-${template.id}` : "note", () => newNote(template?.title ?? "", template?.content ?? ""), onCreated);
  const noteWith = (kind: PendingNoteAction) =>
    run(
      kind,
      async () => {
        const id = await newNote();
        setPendingNoteAction(id, kind);
        return id;
      },
      onCreated,
    );
  const list = () =>
    run("list", async () => (await createList.mutateAsync({ space_id: space!.id, folder_id: targetFolderId })).id, onCreated);
  const table = () =>
    run("table", async () => (await createTable.mutateAsync({ space_id: space!.id, folder_id: targetFolderId })).id, onCreated);
  const ask = () => run("ask", async () => (await createDialog.mutateAsync({})).id, onDialog);
  const link = (url: string) => run("link", () => newNote("", url.trim()), onCreated);

  const tile = (
    kind: string,
    label: string,
    title: string,
    Icon: typeof FileText,
    onClick: () => void,
    opts?: { tone?: "dark" | "lime" | "brand"; hidden?: boolean },
  ) =>
    opts?.hidden ? null : (
      <button
        type="button"
        onClick={onClick}
        disabled={!!busy || !space}
        title={title}
        className={`flex h-[96px] flex-col items-start justify-between rounded-3xl p-3.5 text-left text-sm font-extrabold transition-colors active:scale-[0.98] disabled:opacity-50 ${
          opts?.tone === "dark"
            ? "bg-nav text-nav-text"
            : opts?.tone === "lime"
              ? "bg-lime text-on-lime"
              : opts?.tone === "brand"
                ? "bg-brand text-white"
                : "bg-muted text-primary hover:bg-muted-hover"
        }`}
      >
        {busy === kind ? <Spinner size={22} /> : <Icon size={22} strokeWidth={2.2} />}
        <span className="max-w-full truncate">{label}</span>
      </button>
    );

  const templateIcon: Record<string, typeof FileText> = { meeting: Users, diary: CalendarDays, idea: Lightbulb };
  const vault = !!space?.is_vault;

  return (
    <>
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
          <div className="flex items-center justify-between gap-2 px-1">
            <h2 className="text-2xl font-extrabold tracking-tight text-primary">{t("create.title")}</h2>
            {space && (
              <div className="relative min-w-0">
                <button
                  type="button"
                  onClick={() => setFolderPickerOpen((v) => !v)}
                  aria-label={t("create.where")}
                  className="flex h-9 max-w-[220px] items-center gap-1.5 rounded-full bg-muted px-3 text-[13px] font-bold text-primary"
                >
                  <span className="truncate">
                    {t("create.in")} {space.name}
                    {folderName ? ` › ${folderName}` : ""}
                  </span>
                  <ChevronDown size={14} className="shrink-0" />
                </button>
                {folderPickerOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setFolderPickerOpen(false)} />
                    <div className="absolute right-0 top-full z-20 mt-1 max-h-60 w-60 overflow-y-auto rounded-2xl border bg-surface p-1.5 shadow-lg">
                      <button
                        type="button"
                        onClick={() => {
                          setTargetFolderId(null);
                          setFolderPickerOpen(false);
                        }}
                        className={`flex min-h-10 w-full items-center rounded-xl px-3 text-left text-sm font-bold ${
                          targetFolderId === null ? "bg-brand-soft text-brand-text" : "text-primary hover:bg-muted"
                        }`}
                      >
                        {t("create.noFolder")}
                      </button>
                      {(folders ?? []).map((f) => (
                        <button
                          key={f.id}
                          type="button"
                          onClick={() => {
                            setTargetFolderId(f.id);
                            setFolderPickerOpen(false);
                          }}
                          className={`flex min-h-10 w-full items-center gap-2 rounded-xl px-3 text-left text-sm font-bold ${
                            targetFolderId === f.id ? "bg-brand-soft text-brand-text" : "text-primary hover:bg-muted"
                          }`}
                        >
                          <span aria-hidden="true">{f.icon ?? "📁"}</span>
                          <span className="truncate">{f.name}</span>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2.5">
            {tile("note", t("create.note"), "Новая заметка", FileText, () => note(), { tone: "dark" })}
            {tile("list", t("create.list"), "Новый список", ListChecks, list, { hidden: vault })}
            {tile("table", t("create.table"), "Новая таблица", TableIcon, table, { hidden: vault })}
            {tile("record", t("create.voice"), "Голосовая заметка", Mic, () => noteWith("record"), { tone: "lime", hidden: vault })}
            {tile("photo", t("create.photo"), "Скан или фото", Camera, () => noteWith("photo"))}
            {tile("file", t("create.file"), "Заметка с файлом", FileUp, () => noteWith("file"))}
            {tile("reminder", t("create.reminder"), "Напоминание", AlarmClock, () => setReminderOpen(true))}
            {tile("link", t("create.link"), "Заметка из ссылки", LinkIcon, () => setLinkPrompt(true))}
            {tile("ask", t("create.askShort"), t("create.ask"), Sparkles, ask, { tone: "brand" })}
          </div>

          <div className="mt-4 px-1 text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("create.templates")}</div>
          <div className="-mx-4 mt-2 flex gap-2 overflow-x-auto px-4" style={{ scrollbarWidth: "none" }}>
            {NOTE_TEMPLATES.filter((tpl) => tpl.id !== "blank").map((tpl) => {
              const Icon = templateIcon[tpl.id] ?? FileText;
              return (
                <button
                  key={tpl.id}
                  type="button"
                  onClick={() => note(tpl)}
                  disabled={!!busy || !space}
                  className="flex h-11 shrink-0 items-center gap-2 rounded-2xl border-[1.5px] border-default bg-surface px-3.5 text-sm font-bold text-primary transition-colors hover:bg-muted disabled:opacity-50"
                >
                  {busy === `tpl-${tpl.id}` ? <Spinner size={16} /> : <Icon size={16} />}
                  {tpl.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {linkPrompt && (
        <PromptDialog
          title="Ссылка"
          confirmLabel={t("folders.create")}
          onConfirm={(url) => {
            setLinkPrompt(false);
            if (url.trim()) void link(url);
          }}
          onCancel={() => setLinkPrompt(false)}
        />
      )}
      {reminderOpen && (
        <ReminderModal
          defaultTitle=""
          onCreate={({ title, body, triggerAt, repeat }) => {
            setReminderOpen(false);
            createReminder.mutate(
              { title, body, trigger_at: triggerAt.toISOString(), ...(repeat ? { repeat } : {}) },
              { onSuccess: onClose },
            );
          }}
          onCancel={() => setReminderOpen(false)}
        />
      )}
    </>
  );
}
