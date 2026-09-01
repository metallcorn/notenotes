import { useEditor, EditorContent, BubbleMenu } from "@tiptap/react";
import type { EditorView } from "@tiptap/pm/view";
import StarterKit from "@tiptap/starter-kit";
import LinkExtension from "@tiptap/extension-link";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import { createLowlight, common } from "lowlight";
import { Markdown } from "tiptap-markdown";
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, RefObject } from "react";
import { createPortal } from "react-dom";
import { Archive, ChevronLeft, Code2, Eye, FileText, Globe, History, MoreVertical, Palette, Pencil, Pin, PinOff, Sparkles, Tag as TagIcon, Trash2, Users, WifiOff } from "lucide-react";
import type { Item } from "../api/types";
import { uiStorage, type ContentWidth } from "../lib/storage";
import TableOfContentsPanel from "./TableOfContentsPanel";
import { useVersionCheck } from "../lib/useVersionCheck";
import { getVaultKey } from "../lib/vaultSession";
import { downloadFile, inlineImages, sanitizeFilename, wrapHtmlDocument } from "../lib/export";
import {
  useAddItemTag,
  useAiTransform,
  useArchiveItem,
  useCreateReminder,
  useCreateTag,
  useDeleteItem,
  useFolders,
  useItem,
  useItemBacklinks,
  useMe,
  useMigrateItemToVault,
  useMoveItemSpace,
  useRemoveItemTag,
  useSpaces,
  useSuggestTags,
  useTags,
  useUpdateItem,
  useUploadFile,
} from "../api/hooks";
import VersionHistoryPanel from "./VersionHistoryPanel";
import EditorToolbar from "./EditorToolbar";
import AiMenu, { type AiAction } from "./AiMenu";
import ImageToolbar from "./ImageToolbar";
import VideoToolbar from "./VideoToolbar";
import CodeBlockToolbar from "./CodeBlockToolbar";
import TableToolbar from "./TableToolbar";
import Spinner from "./Spinner";
import ConfirmDialog from "./ConfirmDialog";
import MoveItemModal from "./MoveItemModal";
import ReminderModal from "./ReminderModal";
import NoteAssistantModal from "./NoteAssistantModal";
import ShareNoteModal from "./ShareNoteModal";
import RecordingPanel from "./RecordingPanel";
import ExportMenu from "./ExportMenu";
import { ResizableImage } from "../extensions/ResizableImage";
import { Video } from "../extensions/Video";
import { Audio } from "../extensions/Audio";
import { LinkPreview } from "../extensions/LinkPreview";
import { DocumentAttachment, serializeDocumentAttachment } from "../extensions/DocumentAttachment";
import { UrlCheckAttachment } from "../extensions/UrlCheckAttachment";
import { DeliveryAttachment } from "../extensions/DeliveryAttachment";
import { TicketAttachment } from "../extensions/TicketAttachment";
import { Spacer } from "../extensions/Spacer";
import { HideImageProcessingPlaceholder } from "../extensions/HideImageProcessingPlaceholder";
import { ProcessingPlaceholder } from "../extensions/ProcessingPlaceholder";
import { UploadPlaceholder } from "../extensions/UploadPlaceholder";
import { TrailingParagraph } from "../extensions/TrailingParagraph";
import { Callout } from "../extensions/Callout";
import { NoteLink } from "../extensions/NoteLink";
import { NoteLinkSuggestion } from "../extensions/NoteLinkSuggestion";
import { InlineLinkFavicon } from "../extensions/InlineLinkFavicon";
import { DataRecognition } from "../extensions/DataRecognition";
import { DetectedAddressLinks } from "../extensions/DetectedAddressLinks";
import { ReminderAnchor } from "../extensions/ReminderAnchor";
import { ImageOcrResult } from "../extensions/ImageOcrResult";
import { SlashCommand } from "../extensions/SlashCommand";
import { TableEmbed } from "../extensions/TableEmbed";
import InsertTableModal from "./InsertTableModal";
import { CollabProvider, type CollabStatus } from "../lib/collabProvider";
import { attachCollab, detachCollab } from "../lib/collabState";

// Детерминированный цвет курсора участника из его id — тот же человек
// всегда одного цвета у всех остальных, без координации между клиентами.
const CURSOR_COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#a855f7", "#ec4899"];
function cursorColorForUser(userId: string | undefined): string {
  if (!userId) return CURSOR_COLORS[0];
  let hash = 0;
  for (let i = 0; i < userId.length; i++) hash = (hash * 31 + userId.charCodeAt(i)) >>> 0;
  return CURSOR_COLORS[hash % CURSOR_COLORS.length];
}

// Только когда вставленный текст ЦЕЛИКОМ — голая ссылка (случай "вставил
// ссылку на сайт, чтобы сохранить на потом" — реальный сценарий из
// отзыва). Ссылки внутри обычного текста остаются обычными подчёркнутыми
// ссылками — превращать их в карточки было бы избыточно и ломало бы поток
// чтения.
const BARE_URL_RE = /^https?:\/\/\S+$/;

// Реальный запрос: вставил ссылку на заметку, скопированную из адресной
// строки браузера (?item=<uuid>) — должна распознаться как ссылка на СВОЮ
// заметку (NoteLink.ts), а не превратиться в generic-превью с попыткой
// затянуть og:title с собственного домена. Только СВОЙ origin — ссылка на
// другой self-hosted инстанс Notenotes не должна считаться внутренней.
export function parseInternalNoteLink(rawUrl: string): string | null {
  try {
    const url = new URL(rawUrl);
    if (url.origin !== window.location.origin) return null;
    const itemId = url.searchParams.get("item");
    if (!itemId || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(itemId)) return null;
    return itemId;
  } catch {
    return null;
  }
}

const EmojiPickerPopover = lazy(() => import("./EmojiPickerPopover"));
const lowlight = createLowlight(common);

// "view" — Просмотр (только читать, не редактируется, клавиатура не
// вызывается на мобильном), "wysiwyg" — обычное визуальное редактирование,
// "raw" — редактор Markdown-текста напрямую. Реальная просьба: три режима,
// не два — иногда нужно просто пролистать открытую заметку без риска
// случайно что-то изменить.
type Mode = "view" | "wysiwyg" | "raw";

const MODE_LABEL: Record<Mode, string> = { view: "Просмотр", wysiwyg: "WYSIWYG", raw: "Markdown" };
const MODE_ICON: Record<Mode, typeof Eye> = { view: Eye, wysiwyg: Pencil, raw: Code2 };

const COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#a855f7", "#ec4899"];

// Реальная жалоба: на мобильном вся строка действий (режим/цвет/закрепить/
// поделиться/история/экспорт/архив/удалить) не схлопывалась — заголовку
// заметки не оставалось места тапнуть и переименовать. Портал-в-body — тот
// же приём, что у FolderMenu (FolderTree.tsx)/NoteTemplateMenu
// (NoteList.tsx): позиционируется от кнопки-триггера через
// getBoundingClientRect, не зависит от overflow предков.
function MobileNoteActionsMenu({
  triggerRef,
  item,
  mode,
  switchMode,
  updateItem,
  showColorPicker,
  setShowColorPicker,
  currentSpaceIsPublicPages,
  setShowShareModal,
  setShowHistory,
  handleExport,
  archiveItem,
  setConfirmingDelete,
  deleteItem,
  onClose,
}: {
  triggerRef: RefObject<HTMLButtonElement>;
  item: Item;
  mode: Mode;
  switchMode: (m: Mode) => void;
  updateItem: { mutate: (payload: { id: string; pinned?: boolean; color?: string | null }) => void };
  showColorPicker: boolean;
  setShowColorPicker: (v: boolean | ((prev: boolean) => boolean)) => void;
  currentSpaceIsPublicPages: boolean;
  setShowShareModal: (v: boolean) => void;
  setShowHistory: (v: boolean | ((prev: boolean) => boolean)) => void;
  handleExport: (format: "md" | "html") => Promise<void> | void;
  archiveItem: { mutate: (id: string) => void; isPending: boolean };
  setConfirmingDelete: (v: boolean) => void;
  deleteItem: { isPending: boolean };
  onClose: () => void;
}) {
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);

  useEffect(() => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    setPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
  }, [triggerRef]);

  if (!pos) return null;

  const itemClass = "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-secondary hover:bg-muted-hover";

  return createPortal(
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div style={{ top: pos.top, right: pos.right }} className="fixed z-50 w-56 rounded border bg-surface py-1 shadow-lg">
        <div className="px-3 py-1.5 text-xs font-medium text-subtle">Режим</div>
        {(["view", "wysiwyg", "raw"] as const).map((m) => {
          const ModeIcon = MODE_ICON[m];
          return (
            <button
              key={m}
              onClick={() => switchMode(m)}
              className={`${itemClass} ${mode === m ? "bg-muted font-medium text-primary" : ""}`}
            >
              <ModeIcon size={15} /> {MODE_LABEL[m]}
            </button>
          );
        })}
        <div className="my-1 border-t" />
        <button onClick={() => setShowColorPicker((v) => !v)} className={itemClass}>
          <Palette size={15} /> Цвет заголовка
        </button>
        {showColorPicker && (
          <div className="flex flex-wrap gap-1 px-3 py-2">
            <button
              onClick={() => {
                updateItem.mutate({ id: item.id, color: null });
                setShowColorPicker(false);
              }}
              title="Без цвета"
              className="h-6 w-6 rounded-full border text-xs text-subtle"
            >
              ×
            </button>
            {COLORS.map((c) => (
              <button
                key={c}
                onClick={() => {
                  updateItem.mutate({ id: item.id, color: c });
                  setShowColorPicker(false);
                }}
                style={{ backgroundColor: c }}
                className="h-6 w-6 rounded-full border"
              />
            ))}
          </div>
        )}
        <button
          onClick={() => {
            updateItem.mutate({ id: item.id, pinned: !item.pinned });
            onClose();
          }}
          className={itemClass}
        >
          {item.pinned ? <PinOff size={15} /> : <Pin size={15} />}
          {item.pinned ? "Открепить" : "Закрепить как важное"}
        </button>
        {currentSpaceIsPublicPages && (
          <button
            onClick={() => {
              setShowShareModal(true);
              onClose();
            }}
            className={itemClass}
          >
            <Globe size={15} /> Публичная ссылка
          </button>
        )}
        <button
          onClick={() => {
            setShowHistory((v) => !v);
            onClose();
          }}
          className={itemClass}
        >
          <History size={15} /> История версий
        </button>
        <button
          onClick={() => {
            void handleExport("md");
            onClose();
          }}
          className={itemClass}
        >
          <FileText size={15} /> Экспорт в Markdown
        </button>
        <button
          onClick={() => {
            void handleExport("html");
            onClose();
          }}
          className={itemClass}
        >
          <FileText size={15} /> Экспорт в HTML
        </button>
        <div className="my-1 border-t" />
        <button
          onClick={() => {
            archiveItem.mutate(item.id);
            onClose();
          }}
          disabled={archiveItem.isPending}
          className={`${itemClass} disabled:opacity-50`}
        >
          <Archive size={15} /> В архив
        </button>
        <button
          onClick={() => {
            setConfirmingDelete(true);
            onClose();
          }}
          disabled={deleteItem.isPending}
          className={`${itemClass} text-danger hover:bg-danger/10 disabled:opacity-50`}
        >
          <Trash2 size={15} /> Удалить заметку
        </button>
      </div>
    </>,
    document.body,
  );
}

export default function NoteEditor({
  itemId,
  onDeleted,
  onBack,
  highlightAnchorId,
  onOpenItem,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
  // Клик по ссылке на другую заметку (NoteLink.ts) — переход в приложении,
  // не по href (заметка живёт по /?item=<id>, а не по отдельному URL,
  // который открылся бы новой вкладкой/страницей).
  onOpenItem?: (id: string) => void;
  // Переход из напоминания, поставленного якорем на конкретную строку
  // (см. ReminderAnchor.ts) — прокрутить и подсветить, тот же приём, что
  // highlightEntryId у ListEditor.tsx.
  highlightAnchorId?: string | null;
}) {
  const { data: item, isError, refetch: refetchItem } = useItem(itemId);
  const updateItem = useUpdateItem();
  const deleteItem = useDeleteItem(item?.space_id);
  const archiveItem = useArchiveItem(item?.space_id);
  const uploadFile = useUploadFile(item?.space_id);
  // OCR/расшифровка видео никогда не запускаются для сейфа (бэкенд не
  // видит plaintext) — плейсхолдер "обрабатывается…" никогда не заменился
  // бы, застряв в заметке навсегда. insertImage/insertUploadedFile ниже
  // используют этот флаг, чтобы его не вставлять.
  const isVaultNote = !!(item && getVaultKey(item.space_id));
  const { data: allTags } = useTags();
  const addTag = useAddItemTag(itemId);
  const removeTag = useRemoveItemTag(itemId);
  const suggestTags = useSuggestTags(itemId);
  const { data: backlinks } = useItemBacklinks(itemId);
  const createTag = useCreateTag();
  const { data: folders } = useFolders(item?.space_id);
  const { data: spaces } = useSpaces();
  const { data: me } = useMe();
  const moveItemSpace = useMoveItemSpace();
  const migrateItemToVault = useMigrateItemToVault();
  const aiTransform = useAiTransform();
  const createReminder = useCreateReminder();

  const [mode, setMode] = useState<Mode>(() => uiStorage.getNoteEditorMode());
  const [showToc, setShowToc] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [showHistory, setShowHistory] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [showTagPicker, setShowTagPicker] = useState(false);
  const [tagQuery, setTagQuery] = useState("");
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [pendingSpaceId, setPendingSpaceId] = useState<string | null>(null);
  const [showMoveModal, setShowMoveModal] = useState(false);
  const [showColorPicker, setShowColorPicker] = useState(false);
  // Реальная жалоба: на мобильном вся строка действий (режим/цвет/закрепить/
  // поделиться/история/экспорт/архив/удалить) не схлопывалась — заголовку
  // заметки не оставалось места тапнуть и переименовать. На узких экранах
  // (< md) вся эта группа прячется под одну кнопку "⋮", на md и шире —
  // как раньше, без изменений.
  const [showMobileActions, setShowMobileActions] = useState(false);
  const mobileActionsButtonRef = useRef<HTMLButtonElement>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [reminderModalOpen, setReminderModalOpen] = useState(false);
  const [reminderAnchorPos, setReminderAnchorPos] = useState<number | null>(null);
  const [insertTableModalOpen, setInsertTableModalOpen] = useState(false);
  const [insertTablePos, setInsertTablePos] = useState<number | null>(null);
  const [assistantModalOpen, setAssistantModalOpen] = useState(false);
  const [assistantRange, setAssistantRange] = useState<{ from: number; to: number } | null>(null);
  const [assistantSelectionText, setAssistantSelectionText] = useState<string | null>(null);
  const [contentWidth, setContentWidth] = useState<ContentWidth>(() => uiStorage.getContentWidth());
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadBatch, setUploadBatch] = useState<{ current: number; total: number } | null>(null);
  const [recordingPanelOpen, setRecordingPanelOpen] = useState(false);
  const [recordingInsertPos, setRecordingInsertPos] = useState<number | null>(null);

  const savedRef = useRef({ title: "", content: "" });
  const pendingRef = useRef<{ id: string; title: string; content: string } | null>(null);
  const loadedItemIdRef = useRef<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // editorExtensions ниже собирается один раз (useMemo с []) — тот же
  // приём, что updateAvailableRef: NoteLink.configure({onOpen}) захватил бы
  // ссылку на onOpenItem, актуальную только на момент ПЕРВОГО монтирования
  // (AppShell.tsx передаёт новую функцию-замыкание на каждый свой рендер),
  // и дальше вызывал бы устаревшую версию с устаревшими setViewMode/
  // setSelectedItemId внутри. Обёртка читает ref в момент клика — сама
  // ссылка на функцию стабильна, но всегда достаёт актуальный колбэк.
  const onOpenItemRef = useRef(onOpenItem);
  useEffect(() => {
    onOpenItemRef.current = onOpenItem;
  }, [onOpenItem]);

  // editorProps (handlePaste/handleDrop) ниже собирается через тот же
  // useMemo([]) приём — файлы из буфера обмена (Ctrl+V) и из
  // перетаскивания снаружи (файловый менеджер ОС) — обе реальные жалобы,
  // ни то ни другое раньше вообще ничего не делало — грузятся через
  // pasteFiles, которая замыкает item/editor/uploadFile — все они меняются между
  // рендерами, поэтому доступ только через ref, обновляемый каждый рендер
  // (в отличие от onOpenItemRef, зависимость тут — сразу много изменчивых
  // значений, проще обновлять без списка deps, чем перечислять их все).
  const pasteFilesRef = useRef((_files: File[], _atPos?: number) => {});
  useEffect(() => {
    pasteFilesRef.current = pasteFiles;
  });

  // Совместное редактирование (Yjs) — провайдер живёт, только пока текущая
  // заметка коллаборативна и открыта; collabItemIdRef — id заметки, к
  // которой он реально привязан (сверяется перед фоновым ресинком ниже).
  // switchTokenRef — защита от гонки при быстром переключении между
  // заметками: асинхронный переход, чей номер не совпадает с актуальным
  // на момент завершения шага, бросается, не применяя результат.
  const collabProviderRef = useRef<CollabProvider | null>(null);
  const collabItemIdRef = useRef<string | null>(null);
  const switchTokenRef = useRef(0);
  const [collabStatus, setCollabStatus] = useState<CollabStatus | null>(null);

  // Реальный найденный баг (пойман через отчёт ErrorBoundary — "can't
  // access property destroy, o is null" внутри ReactNodeViewRenderer):
  // инлайновый литерал массива создавал НОВУЮ ссылку при каждом рендере
  // NoteEditor, а useEditor (без deps) на каждый такой рендер вызывает
  // editor.setOptions(...) заново (сравнение по ссылке в @tiptap/react,
  // не по содержимому) — при частых внешних ре-рендерах (например,
  // разблокировка сейфа в другом месте дерева, которая триггерит
  // ре-рендер всего AppShell) это иногда попадало в момент, когда
  // React-NodeView (TicketAttachment/DocumentAttachment/...) ещё не
  // домонтировался или уже размонтировался — и .destroy() дёргался на
  // null. useMemo с пустыми deps даёт стабильную ссылку: все замыкания
  // внутри (imageInputRef, setReminderAnchorPos, setReminderModalOpen)
  // сами по себе стабильны между рендерами (ref и сеттеры useState),
  // так что пустой deps-массив тут безопасен.
  const editorExtensions = useMemo(
    () => [
      StarterKit.configure({ codeBlock: false }),
      CodeBlockLowlight.configure({ lowlight }),
      ResizableImage,
      Video,
      Audio,
      LinkPreview,
      DocumentAttachment,
      UrlCheckAttachment,
      DeliveryAttachment,
      TicketAttachment,
      Spacer,
      ProcessingPlaceholder,
      HideImageProcessingPlaceholder,
      UploadPlaceholder,
      TrailingParagraph,
      Callout,
      NoteLink.configure({ onOpen: (id: string) => onOpenItemRef.current?.(id) }),
      NoteLinkSuggestion,
      InlineLinkFavicon,
      DataRecognition,
      DetectedAddressLinks,
      ReminderAnchor,
      ImageOcrResult,
      TableEmbed,
      LinkExtension.configure({ HTMLAttributes: { target: "_blank", rel: "noopener noreferrer" } }),
      Table.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      Markdown.configure({ html: true, transformPastedText: true }),
      SlashCommand.configure({
        onInsertImage: () => imageInputRef.current?.click(),
        onCreateReminder: (pos: number) => {
          setReminderAnchorPos(pos);
          setReminderModalOpen(true);
        },
        onInsertTable: (pos: number) => {
          setInsertTablePos(pos);
          setInsertTableModalOpen(true);
        },
      }),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // Тот же приём и та же причина, что у editorExtensions выше: editorProps,
  // в отличие от extensions, не разбирается в @tiptap/react особым
  // образом при сравнении — сравнивается по ссылке (compareOptions), а
  // инлайновый объект каждый рендер новый.
  const editorProps = useMemo(
    () => ({
      // Прямой editorProps.handlePaste, а не addPasteRules() у самого узла:
      // у tiptap-markdown включён transformPastedText, который перехватывает
      // вставку текста своим собственным handlePaste ДО обычного механизма
      // paste rules — если положиться на paste rules, превращение ссылки в
      // карточку могло бы вообще не сработать в зависимости от порядка
      // плагинов. editorProps на самом EditorView вызывается раньше любых
      // плагинных handlePaste, так что порядок гарантирован.
      handlePaste: (view: EditorView, event: ClipboardEvent) => {
        const files = Array.from(event.clipboardData?.files ?? []);
        if (files.length) {
          event.preventDefault();
          void pasteFilesRef.current(files);
          return true;
        }
        const text = event.clipboardData?.getData("text/plain")?.trim();
        if (!text || !BARE_URL_RE.test(text)) return false;
        const { state } = view;
        const internalItemId = parseInternalNoteLink(text);
        // title пустой — NoteLinkCard.tsx сам подтянет название по itemId
        // (см. useItemBrief там) и допишет его в атрибут узла при вставке
        // такой ссылки: в момент вставки мы знаем только id из URL.
        const node = internalItemId
          ? state.schema.nodes.noteLink.create({ itemId: internalItemId, title: "" })
          : state.schema.nodes.linkPreview.create({ url: text });
        view.dispatch(state.tr.replaceSelectionWith(node));
        return true;
      },
      // Реальная жалоба: перетащить файл из файлового менеджера ОС в
      // заметку не работало вообще — как и с handlePaste выше, никакого
      // обработчика drop на файлы не было в принципе (перетаскивание
      // самих узлов editor'а — картинок/блоков внутри заметки — отдельный
      // механизм TipTap, drag-handle, он не затронут). ProseMirror по
      // умолчанию ничего не делает с File-объектами из dataTransfer, если
      // им явно не заняться. posAtCoords — вставка ровно там, куда
      // перетащили, а не в текущее выделение (иначе файл мог бы улететь в
      // совсем другое место заметки, если курсор до этого стоял не там).
      handleDrop: (view: EditorView, event: DragEvent) => {
        const files = Array.from(event.dataTransfer?.files ?? []);
        if (!files.length) return false;
        event.preventDefault();
        const coords = view.posAtCoords({ left: event.clientX, top: event.clientY });
        void pasteFilesRef.current(files, coords?.pos);
        return true;
      },
      // Реальная жалоба: "печатаю, жму Enter несколько раз для отступа —
      // визуально вижу пустые строки, но при сохранении/перезагрузке всё
      // пропадает". Причина — лишний ПУСТОЙ абзац в конце документа не
      // меняет сериализованный markdown-текст ни на символ, поэтому
      // onUpdate честно срабатывает, но getMarkdown() возвращает ту же
      // строку — React даже не видит изменения state. Перехват через
      // addKeyboardShortcuts() у расширений (пробовал дважды, разными
      // способами) ненадёжен из-за приоритета keymap-плагинов между
      // расширениями в @tiptap/core — реально не срабатывал на практике.
      // handleKeyDown прямо на EditorView, тот же приём, что уже
      // используется для handlePaste выше — единственный, который
      // подтверждённо сработал при живой проверке (жёсткий перенос
      // реально сохранился в содержимом заметки).
      //
      // Жёсткий перенос строки (hardBreak) вместо разбиения на новый
      // абзац — это НАСТОЯЩИЙ символ в markdown (сериализуется как "\" +
      // перенос строки, tiptap-markdown), не пустая декорация, поэтому не
      // пропадает и не схлопывается, сколько раз подряд Enter ни жми.
      //
      // Реальный найденный регресс первой версии этого фикса: перехват
      // Enter здесь происходит РАНЬШЕ, чем его успевает увидеть плагин
      // Suggestion у SlashCommand.ts (/-меню) — Enter, которым
      // пользователь подтверждает выбор пункта меню ("/отступ" → Enter),
      // вместо этого превращался в перенос строки, а меню просто
      // переставало на Enter/клик реагировать. Проверка textBefore ниже
      // — тот же триггер-паттерн, что у Suggestion (char: "/", без
      // пробела после) — пропускаем перехват, пока слэш-команда набирается.
      //
      // Второй найденный регресс (реальная жалоба): предыдущая версия
      // перехватывала АБСОЛЮТНО КАЖДЫЙ Enter в обычном абзаце — из-за
      // этого нормальное "напечатал текст → Enter → новый абзац" вообще
      // перестало работать, всё превращалось в один абзац с переносами
      // внутри. Перехватывать нужно только ВТОРОЙ Enter подряд (когда
      // абзац, в котором стоит курсор, уже пустой — то есть предыдущий
      // Enter только что создал его штатным способом) — только тогда есть
      // риск потери пустой строки при сохранении; самый первый Enter,
      // разбивающий реальный текст, должен создавать обычный новый абзац.
      handleKeyDown: (view: EditorView, event: KeyboardEvent) => {
        if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) {
          return false;
        }
        const { state } = view;
        const { $from, empty } = state.selection;
        if (!empty || $from.depth !== 1 || $from.parent.type.name !== "paragraph") {
          return false;
        }
        if ($from.parent.textContent.length > 0) return false;
        const textBefore = $from.parent.textBetween(0, $from.parentOffset, undefined, "￼");
        if (/\/\S*$/.test(textBefore)) return false;
        const hardBreak = state.schema.nodes.hardBreak;
        if (!hardBreak) return false;
        view.dispatch(state.tr.replaceSelectionWith(hardBreak.create(), false).scrollIntoView());
        return true;
      },
    }),
    [],
  );

  const editor = useEditor({
    extensions: editorExtensions,
    content: "",
    editorProps,
    onUpdate: ({ editor }) => setContent(editor.storage.markdown.getMarkdown()),
  });

  // Заметки больше нет (удалили в другой вкладке, или это протухшая ссылка
  // «последняя открытая заметка» из localStorage) — не зависаем на вечной
  // загрузке, а просто сбрасываем выбор. Именно !item, а не только isError:
  // офлайн (ТЗ §18) фоновый рефетч тоже падает в isError, но кэшированный
  // item при этом на месте — раньше это забрасывало обратно в "выберите
  // заметку" при каждой открытой офлайн заметке (тот же паттерн бага, что
  // был в App.tsx:RequireAuth, только там про сессию, тут про саму заметку).
  useEffect(() => {
    if (isError && !item) onDeleted();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isError]);

  // Заметку сменили — подгружаем её состояние в редактор заново. Для
  // заметок в шареном (не vault) спейсе дополнительно поднимаем живое
  // совместное редактирование (Yjs, см. lib/collabState.ts) — один
  // стабильный editor переиспользуется для всех заметок, поэтому сначала
  // ПОЛНОСТЬЮ отключаемся от предыдущей коллаборативной заметки (если
  // была), и только потом подключаемся к новой — строго по очереди,
  // никогда одновременно (см. обсуждение гонки при быстром переключении).
  // Реальный найденный баг: раньше эффект зависел от ВСЕГО массива spaces —
  // react-query переспрашивает его при возврате фокуса на вкладку (в т.ч.
  // ровно после закрытия нативного диалога выбора файла, как при вставке
  // картинки), и даже при абсолютно тех же данных возвращает НОВУЮ ссылку
  // на массив, из-за чего эффект перезапускался целиком — отключал и
  // заново подключал коллаборацию у уже открытой заметки, сбрасывая
  // курсор ровно в момент, когда пользователь только что вставил файл и
  // собирался печатать дальше. Эффект должен реагировать только на
  // изменение ОДНОГО конкретного примитива (та самая заметка стала/
  // перестала быть vault), а не на переспрос всего списка спейсов.
  const currentSpaceIsVault = spaces?.find((s) => s.id === item?.space_id)?.is_vault ?? null;
  // Кнопка «Поделиться» видна только для заметок в спейсе «Публичные
  // страницы» (routers/items.py::share_item отклонит попытку для любого
  // другого спейса всё равно, но незачем показывать кнопку там, где она
  // гарантированно откажет).
  const currentSpaceIsPublicPages = spaces?.find((s) => s.id === item?.space_id)?.is_public_pages ?? false;

  useEffect(() => {
    if (!item || !editor) return;
    const token = ++switchTokenRef.current;
    const isStale = () => switchTokenRef.current !== token;
    // 2026-08-19: живое совместное редактирование ненадолго отключалось —
    // заметку "Подарок на день рождения" правили одновременно в двух браузерах И
    // через Telegram-ассистента, и она несколько раз опустела. Найденная и
    // закрытая причина: ассистентские тулы update_note/append_to_note
    // (tools/notes.py), и два фоновых воркера (note_recording.py,
    // transcription.py — доделывают расшифровку поверх плейсхолдера) писали
    // в item.content НАПРЯМУЮ, в обход Yjs, и не звали
    // collab.invalidate_room — точно тот же класс бага, что раньше уже был
    // найден и исправлен для vision.py/pdf_processing.py/tickets.py, просто
    // пропущенный в 4 остальных местах. Без invalidate_room открытая с живой
    // коллаборацией заметка не узнавала о чужой правке, и следующий же
    // автосейв из УСТАРЕВШЕГО Yjs-состояния молча затирал её обратно —
    // отсюда и метания content между версиями. Второй, отдельный источник
    // риска — гонка при переключении между заметками (см. isFirstLoadOfThisItem
    // ниже) — тоже сужена. См. [[project_realtime_collab_data_loss]] в
    // памяти сессий.
    const collabEligible = currentSpaceIsVault === false;

    (async () => {
      if (collabProviderRef.current) {
        detachCollab(editor, collabProviderRef.current);
        collabProviderRef.current = null;
        collabItemIdRef.current = null;
      }
      if (isStale()) return;

      // Реальный найденный баг: "вставляю ссылку — заметка её не
      // сохраняет и ссылка тупо пропадает". Между тем, как заметка
      // создаётся (POST) и тем, как этот эффект реально получает её
      // содержимое (GET, а для совместных заметок — ещё и подключение к
      // Yjs-комнате, attachCollab ниже) есть настоящий сетевой зазор.
      // Если пользователь успел вставить/напечатать что-то в редакторе
      // ДО того, как этот эффект досюда добежал, код ниже слепо
      // перезаписывал И React state (setContent), И сам документ
      // редактора (editor.commands.setContent / editor.view.updateState
      // внутри attachCollab) содержимым с сервера, которое ещё ничего не
      // знает об этой правке — вставленное визуально исчезало из
      // редактора и никогда не попадало в автосохранение (действительно
      // "не вводится"/"пропадает", а не проблема сети или деплоя). Раз
      // это ПЕРВАЯ загрузка именно этого id (loadedItemIdRef ещё не
      // совпадает) — текущее содержимое редактора может быть тем, что
      // пользователь уже успел ввести, а не мусором от предыдущей
      // заметки: берём его за основу вместо ответа сервера.
      // Реальный найденный баг (2026-08-19): этот же код срабатывал и при
      // ПЕРЕКЛЮЧЕНИИ между двумя разными существующими заметками, не только
      // при создании новой — редактор один на все заметки, и между тем, как
      // сменился itemId, и тем, как этот эффект реально дошёл до этой
      // строки, DOM редактора ещё показывает содержимое ПРЕДЫДУЩЕЙ заметки.
      // Если оно было непустым, код ниже принимал его за "непойманную
      // правку" уже НОВОЙ заметки и сохранял его поверх неё — чужой текст
      // (или пустота, если предыдущая заметка была пуста) затирал реальное
      // содержимое. Это и есть один из механизмов, приведших к потере
      // контента в живой заметке (см. [[project_realtime_collab_data_loss]]
      // в памяти сессий). Ограничиваем защиту её изначальным смыслом:
      // "пользователь напечатал в СОВСЕМ НОВУЮ заметку до ответа сервера" —
      // сервер для такой заметки ещё гарантированно ничего не знает, то есть
      // item.content с сервера пуст. Если сервер уже прислал непустой
      // content — значит редактор точно показывает не эту заметку, и его
      // содержимое надо просто отбросить, не сохранять.
      const isFirstLoadOfThisItem = loadedItemIdRef.current !== item.id;
      const liveMarkdown = isFirstLoadOfThisItem && !item.content.trim() ? editor.storage.markdown.getMarkdown() : "";
      const hasUnseenLocalEdit = liveMarkdown.trim() !== "";
      const effectiveContent = hasUnseenLocalEdit ? liveMarkdown : item.content;

      setTitle(item.title);
      setContent(effectiveContent);
      // content: "" (не effectiveContent) — если есть незамеченная правка,
      // это специально делает её "ещё не сохранённой" для дебаунс-эффекта
      // ниже (сравнение content !== savedRef.current.content), чтобы он
      // реально досохранил её на сервер, а не посчитал состояние уже
      // синхронизированным.
      savedRef.current = { title: item.title, content: hasUnseenLocalEdit ? "" : item.content };
      loadedItemIdRef.current = item.id;

      if (!collabEligible) {
        if (!hasUnseenLocalEdit) {
          editor.commands.setContent(item.content || "");
          // Реальный найденный баг: просто ОТКРЫЛ заметку, ничего не менял —
          // она подскакивала в топ списка, создавалась лишняя версия.
          // TrailingParagraph (extensions/TrailingParagraph.ts) молча
          // дописывает пустой абзац, если заметка заканчивается атом-узлом
          // (карточка ссылки/вложения/билет) — полезно, чтобы можно было
          // кликнуть и печатать после него, но onUpdate после этого видит
          // "новый" markdown, который не совпадает с savedRef.current.content
          // (тем сырым, что пришло с сервера ДО нормализации) — автосейв
          // считает это настоящей правкой пользователя. Синхронизируем
          // базовую точку с тем, что РЕАЛЬНО оказалось в редакторе после
          // setContent (уже с учётом любой такой нормализации), а не с
          // сырым серверным значением — тогда нечего "досохранять".
          const normalized = editor.storage.markdown.getMarkdown();
          setContent(normalized);
          savedRef.current = { ...savedRef.current, content: normalized };
        }
        setStatus(hasUnseenLocalEdit ? "saving" : "idle");
        setCollabStatus(null);
        return;
      }

      setCollabStatus("connecting");
      const provider = new CollabProvider(item.id, (s) => {
        if (!isStale()) setCollabStatus(s);
      });
      try {
        await attachCollab(editor, editorExtensions, provider, effectiveContent || "", {
          name: me?.name ?? "?",
          color: cursorColorForUser(me?.id),
        });
      } catch {
        // Не удалось подключиться — блокируем редактирование этой заметки
        // явно (setEditable ниже реагирует на collabStatus), а не тихо
        // откатываемся на локальное редактирование без синхронизации —
        // осознанный выбор простоты и предсказуемости.
        provider.disconnect();
        if (!isStale()) setCollabStatus("disconnected");
        return;
      }
      if (isStale()) {
        // Успели уйти с этой заметки, пока шло подключение — не оставляем
        // висящее соединение и не трогаем редактор, которым уже владеет
        // следующий переход.
        provider.disconnect();
        return;
      }
      collabProviderRef.current = provider;
      collabItemIdRef.current = item.id;
      // Та же причина, что в некомлаб-ветке выше: attachCollab (см.
      // lib/collabState.ts) намеренно дёргает пустой dispatch сразу после
      // подключения, чтобы TrailingParagraph успел дописать абзац после
      // хвостового атом-узла — это меняет editor.storage.markdown.
      // getMarkdown() относительно сырого item.content, на которое уже
      // указывает savedRef.current (строка выше, до attachCollab).
      // Досогласовываем базовую точку — иначе автосейв через пару секунд
      // молча "досохранит" эту нормализацию как правку пользователя (баг:
      // просто открыл заметку, ничего не трогал — она подскочила в топ
      // списка и обзавелась лишней версией).
      const normalized = editor.storage.markdown.getMarkdown();
      setContent(normalized);
      savedRef.current = { ...savedRef.current, content: normalized };
      setStatus("idle");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id, editor, currentSpaceIsVault]);

  // Заблокировать редактирование, пока совместная заметка подключается
  // или если связь оборвалась — осознанное решение (см. обсуждение):
  // проще и безопаснее, чем тихо давать печатать локально без синка.
  useEffect(() => {
    if (!editor) return;
    editor.setEditable(collabStatus !== "connecting" && collabStatus !== "disconnected" && collabStatus !== "stale");
  }, [editor, collabStatus]);

  // Переподключение к живой коллаборации. Два повода:
  //  - "stale" — сервер сам разорвал комнату (app/collab.py::invalidate_room,
  //    фоновый воркер/ассистент поменял content в обход Yjs) — переподключаемся
  //    сразу, без задержки.
  //  - "disconnected" — обычный обрыв WS (реальный случай: мобильная сеть
  //    рвёт соединение при сворачивании браузера в фон, без явного закрытия)
  //    — раньше на этот случай реконнекта не было вообще: заметка молча
  //      становилась read-only и не восстанавливалась сама, пока пользователь
  //      не откроет её заново. Теперь пробуем сами, с небольшой задержкой
  //      (не долбим сервер, если сеть правда легла надолго).
  // В обоих случаях содержимое запрашивается ЗАНОВО с сервера, а не берётся
  // из состояния на момент предыдущего подключения — иначе следующий же
  // автосейв из устаревшего Yjs-состояния молча затёр бы то, что реально
  // изменилось, пока связи не было.
  useEffect(() => {
    if ((collabStatus !== "stale" && collabStatus !== "disconnected") || !editor || !item) return;
    const token = ++switchTokenRef.current;
    const isStaleAttempt = () => switchTokenRef.current !== token;
    const reconnectDelayMs = collabStatus === "disconnected" ? 2000 : 0;

    const timer = setTimeout(() => {
      if (isStaleAttempt()) return;
      void (async () => {
      if (collabProviderRef.current) {
        detachCollab(editor, collabProviderRef.current);
        collabProviderRef.current = null;
        collabItemIdRef.current = null;
      }
      const fresh = await refetchItem();
      const freshContent = fresh.data?.content ?? "";
      if (isStaleAttempt()) return;

      setCollabStatus("connecting");
      const provider = new CollabProvider(item.id, (s) => {
        if (!isStaleAttempt()) setCollabStatus(s);
      });
      try {
        await attachCollab(editor, editorExtensions, provider, freshContent, {
          name: me?.name ?? "?",
          color: cursorColorForUser(me?.id),
        });
      } catch {
        provider.disconnect();
        if (!isStaleAttempt()) setCollabStatus("disconnected");
        return;
      }
      if (isStaleAttempt()) {
        provider.disconnect();
        return;
      }
      collabProviderRef.current = provider;
      collabItemIdRef.current = item.id;
      // Та же причина, что в основном эффекте загрузки выше: attachCollab
      // может дописать TrailingParagraph-абзац — берём то, что РЕАЛЬНО
      // оказалось в редакторе, не голый freshContent с сервера, иначе
      // переподключение само по себе создаёт лишнюю версию/автосейв.
      const normalized = editor.storage.markdown.getMarkdown();
      setContent(normalized);
      savedRef.current = { ...savedRef.current, content: normalized };
      })();
    }, reconnectDelayMs);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collabStatus]);

  // Компонент размонтировался (переключились на другой viewMode —
  // Активность/Корзина/Ассистент — сам NoteEditor размонтируется) — не
  // оставляем открытое WS-соединение висеть.
  useEffect(() => {
    return () => {
      if (collabProviderRef.current && editor) {
        detachCollab(editor, collabProviderRef.current);
        collabProviderRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor]);

  // TicketAttachmentCard.tsx читает это при клике "Напомнить" — см.
  // комментарий в TicketAttachment.ts про то, почему storage, а не проп.
  useEffect(() => {
    if (!editor) return;
    editor.storage.ticketAttachment.itemId = item?.id ?? null;
    editor.storage.ticketAttachment.spaceId = item?.space_id ?? null;
  }, [editor, item?.id, item?.space_id]);

  // Найденные LLM адреса (app/autotag.py) — тот же storage-приём, что у
  // ticketAttachment выше. В отличие от него, decorations() читает это
  // значение на каждый рендер вью, а не по клику — простого обновления
  // storage недостаточно, ProseMirror не знает, что нужно пересчитать
  // декорации, пока не увидит транзакцию; пустая tr — стандартный приём
  // "перерисовать вью по внешнему изменению состояния".
  useEffect(() => {
    if (!editor) return;
    editor.storage.detectedAddressLinks.addresses = item?.detected_addresses ?? [];
    editor.view.dispatch(editor.state.tr);
  }, [editor, item?.detected_addresses]);

  // Переход из напоминания, поставленного якорем (ReminderAnchor.ts) —
  // прокрутить и подсветить, тот же приём, что highlightEntryId у
  // ListEditor.tsx (highlightedRef, а не просто зависимость от id — иначе
  // каждый фоновый refetch заметки переигрывал бы подсветку заново, пока
  // пользователь сидит на странице).
  const highlightedAnchorRef = useRef<string | null>(null);
  useEffect(() => {
    if (!editor || !highlightAnchorId || !item) return;
    if (highlightedAnchorRef.current === highlightAnchorId) return;
    const el = editor.view.dom.querySelector<HTMLElement>(`[data-reminder-id="${highlightAnchorId}"]`);
    if (!el) return;
    highlightedAnchorRef.current = highlightAnchorId;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("reminder-anchor-highlight");
    setTimeout(() => el.classList.remove("reminder-anchor-highlight"), 2500);
  }, [editor, highlightAnchorId, item]);

  // Ту же заметку могли обновить в фоне, пока она открыта — например,
  // распознавание PDF/картинки/видео закончилось и плейсхолдер
  // "обрабатывается…" заменился на готовый результат (useSpaceSync
  // инвалидирует запрос конкретной заметки на WS-сигнал). Подхватываем
  // это, только если у пользователя нет своих несохранённых правок —
  // иначе следующий автосейв тут же затёр бы фоновый результат обратно
  // устаревшим текстом (реально пойманный баг: карточка так и оставалась
  // плейсхолдером навсегда).
  //
  // Реальный найденный баг (мобильная загрузка нескольких фото подряд):
  // hasPendingLocalEdit защищает только от затирания уже НАБРАННОГО текста
  // — но при пакетной загрузке (onPickImage) картинки вставляются
  // командами editor.chain()...run() между await'ами сетевой загрузки.
  // Если распознавание ПЕРВОЙ картинки успевает завершиться и прилетает
  // WS-уведомление, пока editor только что синхронно вставил ВТОРУЮ (но
  // React ещё не перерендерил content-state), это окно между вставкой в
  // ProseMirror и обновлением content успевало проскочить проверку —
  // setContent(item.content) с сервера подменял собой весь документ и
  // безвозвратно стирал только что вставленную, ещё не сохранённую
  // картинку. uploadBatch — явный флаг "идёт пакетная загрузка", не
  // зависящий от таймингов React-рендера — откладываем подхват фонового
  // результата до её завершения (см. onPickImage/onPickFile: там же
  // refetchItem() досогласовывает пропущенное по её окончании).
  useEffect(() => {
    if (!item || item.id !== loadedItemIdRef.current) return;
    // Пока у этой заметки живо совместное редактирование, за синхронизацию
    // содержимого отвечает Yjs (см. эффект выше) — грубая перезапись всего
    // документа отсюда поверх него не читает, а ЛОМАЕТ привязку sync-плагина
    // к содержимому редактора.
    if (collabItemIdRef.current === item.id) return;
    if (uploadBatch) return;
    if (item.content === savedRef.current.content) return;
    const hasPendingLocalEdit = content !== savedRef.current.content || title !== savedRef.current.title;
    if (hasPendingLocalEdit) return;
    setContent(item.content);
    savedRef.current = { ...savedRef.current, content: item.content };
    editor?.commands.setContent(item.content || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.content, uploadBatch]);

  // Автосохранение с дебаунсом. Каждое изменение title/content создаёт
  // на бэкенде запись в item_versions — поэтому не сохраняем на каждый
  // символ, а ждём паузы в наборе.
  //
  // Реальный найденный инцидент (2026-08-19): устаревшая открытая вкладка
  // (старый JS-бандл, загруженный до сегодняшних деплоев) молча продолжала
  // слать автосейв СВОИМ давно не обновлявшимся локальным состоянием —
  // трижды за день затирала то, что только что восстановили в свежей
  // вкладке. updateAvailableRef — тот же сигнал, что показывает баннер в
  // AppShell.tsx, здесь используется как физический стоп-кран: устаревший
  // клиент попросту перестаёт писать на сервер, даже если баннер никто не
  // заметил.
  const updateAvailable = useVersionCheck();
  const updateAvailableRef = useRef(updateAvailable);
  useEffect(() => {
    updateAvailableRef.current = updateAvailable;
  }, [updateAvailable]);

  useEffect(() => {
    if (!item) return;
    if (title === savedRef.current.title && content === savedRef.current.content) {
      pendingRef.current = null;
      return;
    }
    pendingRef.current = { id: item.id, title, content };
    setStatus("saving");
    const timer = setTimeout(() => {
      if (updateAvailableRef.current) return;
      updateItem.mutate({ id: item.id, title, content });
      savedRef.current = { title, content };
      pendingRef.current = null;
      setStatus("saved");
    }, 1200);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, content]);

  // Переключились на другую заметку, пока предыдущая ещё не сохранилась —
  // досохраняем немедленно, а не теряем последние правки.
  useEffect(() => {
    return () => {
      const pending = pendingRef.current;
      if (pending && !updateAvailableRef.current) {
        updateItem.mutate({ id: pending.id, title: pending.title, content: pending.content });
        pendingRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemId]);

  function switchMode(next: Mode) {
    if (next === mode || !editor) return;
    if (next === "raw") {
      setContent(editor.storage.markdown.getMarkdown());
    } else if (mode === "raw") {
      // Из raw в любой из двух режимов рендера — синхронизируем редактор с
      // тем, что напечатано в Markdown. Между "view" и "wysiwyg" редактор
      // трогать не нужно — это один и тот же смонтированный документ,
      // разница только в editable (см. эффект ниже).
      editor.commands.setContent(content || "");
    }
    setMode(next);
    uiStorage.setNoteEditorMode(next);
  }

  // editable, а не отдельный проп в useEditor(...) — та же причина, что и
  // у комментария про editorExtensions/editorProps выше: надёжнее явно
  // дёрнуть editor.setEditable, чем полагаться на то, что @tiptap/react
  // подхватит новое значение внутри options-объекта на очередной рендер.
  useEffect(() => {
    editor?.setEditable(mode !== "view");
  }, [editor, mode]);

  // Без выделения — вся заметка целиком (заменяем весь документ). С
  // выделением — только выбранный фрагмент.
  //
  // ВАЖНО: textBetween() (то, что было тут раньше) вытаскивает ЧИСТЫЙ
  // текст без marks — ссылки, жирный и т.д. терялись ещё до отправки в
  // модель, до всякого промпта (реальная жалоба: пропадали ссылки при
  // переформатировании выделенного текста). editor.storage.markdown
  // .serializer.serialize() принимает произвольный Fragment, не только
  // весь документ — им можно сериализовать именно slice выделения С
  // marks. Симметрично при вставке: insertContentAt в этой библиотеке
  // патчится так, что парсит markdown (включая [text](url) обратно в
  // настоящую ссылку), а не вставляет как голый текст — plain insertContent
  // так не умеет.
  async function applyAiAction(action: AiAction, instruction?: string) {
    if (!editor || aiLoading) return;
    const { from, to, empty } = editor.state.selection;
    const text = empty
      ? editor.storage.markdown.getMarkdown()
      : editor.storage.markdown.serializer.serialize(editor.state.doc.slice(from, to).content);
    if (!text.trim()) return;

    setAiError(null);
    setAiLoading(true);
    editor.setEditable(false);
    try {
      const { result } = await aiTransform.mutateAsync({ action, text, instruction });
      if (empty) {
        editor.commands.setContent(result);
        setContent(result);
      } else {
        editor.chain().focus().insertContentAt({ from, to }, result).run();
      }
    } catch {
      setAiError("Не получилось выполнить действие ИИ — попробуй ещё раз");
      setTimeout(() => setAiError(null), 4000);
    } finally {
      editor.setEditable(true);
      setAiLoading(false);
    }
  }

  // Реальный запрос: "выделил название заведения — хочу, чтобы ассистент
  // нашёл его в интернете и предложил обновить/обогатить заметку". В
  // отличие от applyAiAction выше (текстовое преобразование без тулов) —
  // открывает полноценный мини-чат (NoteAssistantModal.tsx, тулы web_search/
  // search_base/read_website), а не одноразовый запрос. Диапазон выделения
  // запоминаем на момент открытия, не читаем заново на момент "применить" —
  // пока идёт чат, курсор/выделение в редакторе давно могли уйти куда
  // угодно (пользователь мог продолжать читать заметку).
  function openAssistant() {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    if (from === to) {
      setAssistantRange(null);
      setAssistantSelectionText(null);
    } else {
      setAssistantRange({ from, to });
      setAssistantSelectionText(editor.state.doc.textBetween(from, to, " "));
    }
    setAssistantModalOpen(true);
  }

  function applyFromAssistant(text: string) {
    if (!editor) return;
    if (assistantRange) {
      editor.chain().focus().insertContentAt(assistantRange, text).run();
    } else {
      // Не было выделения — не заменяем всю заметку целиком (в отличие от
      // applyAiAction'а: там это осознанный выбор для summarize/reformat,
      // здесь результат — НОВАЯ информация, потеря существующего текста
      // была бы реальной потерей данных), дописываем в конец.
      const end = editor.state.doc.content.size;
      editor.chain().focus().insertContentAt(end, "\n\n" + text).run();
    }
  }

  // Реальный запрос: "хочу записать встречу/длинную заметку прямо в
  // редакторе, с диаризацией" — RecordingPanel.tsx открывается отдельной
  // подпанелью (не блокирует саму заметку, можно продолжать печатать/
  // вставлять картинки, пока идёт запись). Позицию курсора фиксируем в
  // момент клика по кнопке-микрофону, не в момент реального начала
  // записи — пока пользователь смотрит на панель и решает, начинать ли,
  // курсор мог уйти куда угодно.
  function openRecorder() {
    if (!editor) return;
    setRecordingInsertPos(editor.state.selection.from);
    setRecordingPanelOpen(true);
  }

  function onRecordingStarted(uploadId: string) {
    if (!editor || recordingInsertPos === null) return;
    // Плейсхолдер — точная строка, которую backend ищет и заменяет на
    // готовый плеер + сворачиваемую расшифровку (app/note_recording.py,
    // placeholder_text()); должна совпадать 1:1. Обычный текст, не новый
    // абзац — вставляется прямо в позицию курсора, а не после неё как у
    // insertImage, курсор мог стоять посреди уже существующего текста.
    const placeholder = `⏳ Запись ${uploadId} расшифровывается…`;
    editor.chain().insertContentAt(recordingInsertPos, placeholder).run();
  }

  // Сейф: сразу после загрузки content ещё указывает прямо на
  // /api/uploads/{id} — те же байты, что только что зашифровал
  // useUploadFile. Расшифровка URL в blob: (decryptUploadUrlsInContent,
  // api/hooks.ts) срабатывает только при СЛЕДУЮЩЕЙ загрузке заметки с
  // сервера, а не для узла, только что вставленного в текущий, ещё не
  // сохранённый документ — без этого патча пользователь увидел бы
  // сломанную картинку/видео сразу после аплоада вместо своего файла.
  // Патчим напрямую DOM только что вставленного узла — сам атрибут src в
  // документе ProseMirror (и то, что попадёт в сохранённый markdown)
  // остаётся неизменным (/api/uploads/{id}), меняется только то, что
  // физически показывает браузер прямо сейчас.
  function patchLocalPreview(tag: "img" | "video" | "audio", uploadUrl: string, file: File) {
    if (!editor) return;
    const previewUrl = URL.createObjectURL(file);
    requestAnimationFrame(() => {
      const el = editor.view.dom.querySelector(`${tag}[src="${uploadUrl}"]`);
      if (el) el.setAttribute("src", previewUrl);
    });
  }

  // Одна загруженная картинка — общий путь для обеих кнопок («Картинка» И
  // «Файл»): реальная жалоба — картинка, выбранная через «Файл» (обычный
  // системный пикер на телефоне не отличает кнопки), раньше попадала в
  // generic documentAttachment-карточку вместо изображения. Бэкенд всё
  // равно ставил vision-OCR в очередь (content_type определяется по
  // самому файлу, не по кнопке) — а плейсхолдер, на который воркер должен
  // заменить готовый результат, никогда не вставлялся, поэтому результат
  // молча терялся (_replace_in_referencing_items не находил, куда
  // вписать). Единая функция закрывает оба входа сразу.
  // Реальный найденный баг (несколько фото подряд с телефона): вставка
  // через editor.chain().focus().setImage(...).insertContent(...).run()
  // опиралась на ТЕКУЩЕЕ выделение — а между фото в пачке есть await
  // сетевой загрузки, и на телефоне за это время меняется фокус страницы
  // (нативный пикер файла поверх вкладки). Живой случай подтверждён по
  // истории версий заметки: первое же автосохранение уже не содержало
  // картинки — только текст плейсхолдера, то есть setImage() внутри
  // чейна тихо не сработал (проглочен, insertContent с плейсхолдером
  // после него — уже нет). Фикс — явная позиция вставки, не зависящая от
  // live-выделения: insertContentAt(pos, [...]) одним вызовом, картинка
  // и плейсхолдер как единый content-массив (не два раздельных чейн-шага,
  // где один может выполниться без другого). Функция возвращает позицию
  // ПОСЛЕ вставленного — следующий файл в пачке продолжает оттуда же, а
  // не заново от live-selection.
  function insertImageAt(
    pos: number | { from: number; to: number },
    uploaded: { id: string; url: string },
    sourceFile?: File,
  ): number {
    // Плейсхолдер — точная строка, которую backend ищет и заменяет на
    // готовое описание/OCR (app/vision.py, placeholder_text()); должна
    // совпадать 1:1, тот же приём, что и у видео-расшифровки. В сейфе
    // OCR никогда не запускается (бэкенд не видит plaintext) — плейсхолдер
    // никто не заменит, вставлять его там нельзя, застрянет навсегда.
    const placeholder = `⏳ Описание изображения ${uploaded.id} обрабатывается…`;
    let nextPos = typeof pos === "number" ? pos : pos.from;
    if (mode === "wysiwyg" && editor) {
      const content: Record<string, unknown>[] = [{ type: "image", attrs: { src: uploaded.url } }];
      if (!isVaultNote) content.push({ type: "paragraph", content: [{ type: "text", text: placeholder }] });
      editor.chain().focus().insertContentAt(pos, content).run();
      nextPos = editor.state.selection.to;
    } else {
      setContent((c) => `${c}\n\n![](${uploaded.url})\n\n${isVaultNote ? "" : placeholder + "\n"}`);
    }
    if (isVaultNote && sourceFile) patchLocalPreview("img", uploaded.url, sourceFile);
    return nextPos;
  }

  function insertUploadedFileAt(
    pos: number | { from: number; to: number },
    uploaded: {
      id: string;
      url: string;
      filename: string;
      content_type: string;
      pdf_text: string | null;
      pdf_ocr_queued: boolean;
      preview_text: string | null;
      size_bytes: number;
    },
    sourceFile?: File,
  ): number {
    if (uploaded.content_type.startsWith("image/")) {
      return insertImageAt(pos, uploaded, sourceFile);
    }
    const isVideo = uploaded.content_type.startsWith("video/");
    const isAudio = uploaded.content_type.startsWith("audio/");
    // Плейсхолдер — точная строка, которую backend ищет и заменяет на
    // готовый результат (app/transcription.py, placeholder_text()) —
    // держать в одном месте на фронте не получится, но текст должен
    // совпадать 1:1, иначе замена не найдёт, куда вписать результат. В
    // сейфе расшифровка видео не запускается (uploads.py) — как и с
    // картинкой, плейсхолдер вставлять незачем.
    //
    // PDF — по-другому: реальная жалоба, что на время распознавания
    // карточка файла целиком подменялась текстовым плейсхолдером,
    // пользователь терял доступ к самому файлу (открыть/скачать) до конца
    // обработки. Теперь карточка (documentAttachment) вставляется сразу
    // с processing=true — backend меняет только этот флаг на готовый
    // текст (pdf_processing.py::_replace_document_card), url/filename
    // остаются тем же узлом всё время.
    const placeholder = `⏳ Расшифровка ${uploaded.id} обрабатывается…`;
    // Аудио — сразу готовый плеер, без плейсхолдера: расшифровка для
    // отдельно загруженных аудиофайлов не подключена (только для видео),
    // плеер сам по себе и есть превью, ждать нечего.
    const previewText = uploaded.pdf_text ?? uploaded.preview_text ?? "";
    let nextPos = typeof pos === "number" ? pos : pos.from;
    if (mode === "wysiwyg" && editor) {
      if (isVideo) {
        const content: Record<string, unknown>[] = [
          { type: "video", attrs: { src: uploaded.url, filename: uploaded.filename, size: uploaded.size_bytes || null } },
        ];
        if (!isVaultNote) content.push({ type: "paragraph", content: [{ type: "text", text: placeholder }] });
        editor.chain().focus().insertContentAt(pos, content).run();
        nextPos = editor.state.selection.to;
        if (isVaultNote && sourceFile) patchLocalPreview("video", uploaded.url, sourceFile);
      } else if (isAudio) {
        editor
          .chain()
          .focus()
          .insertContentAt(pos, { type: "audio", attrs: { src: uploaded.url, filename: uploaded.filename } })
          .run();
        nextPos = editor.state.selection.to;
        if (isVaultNote && sourceFile) patchLocalPreview("audio", uploaded.url, sourceFile);
      } else {
        editor
          .chain()
          .focus()
          .insertContentAt(pos, {
            type: "documentAttachment",
            attrs: {
              url: uploaded.url,
              filename: uploaded.filename,
              text: uploaded.pdf_ocr_queued ? "" : previewText,
              processing: uploaded.pdf_ocr_queued,
            },
          })
          .run();
        nextPos = editor.state.selection.to;
      }
    } else if (isVideo) {
      const sizeAttr = uploaded.size_bytes ? ` data-size="${uploaded.size_bytes}"` : "";
      setContent(
        (c) =>
          `${c}\n\n<video src="${uploaded.url}" controls preload="metadata" style="max-width: 100%; max-height: 70vh;"${sizeAttr}></video>\n\n${isVaultNote ? "" : placeholder + "\n"}`,
      );
    } else if (isAudio) {
      setContent(
        (c) => `${c}\n\n<audio src="${uploaded.url}" controls preload="metadata" style="max-width: 100%;"></audio>\n`,
      );
    } else {
      setContent(
        (c) =>
          `${c}\n\n${serializeDocumentAttachment(uploaded.url, uploaded.filename, uploaded.pdf_ocr_queued ? "" : previewText, uploaded.pdf_ocr_queued)}\n`,
      );
    }
    return nextPos;
  }

  // Находит по tempId ещё живой узел-плейсхолдер в АКТУАЛЬНОМ документе —
  // не по запомненной позиции: за время await сетевой загрузки пользователь
  // мог напечатать что-то ещё в другом месте заметки, позиции сместились
  // бы. Если плейсхолдер не найден (например, кто-то вручную его удалил,
  // пока файл грузился) — null, вызывающий код падает обратно на текущую
  // позицию курсора.
  function findPlaceholderRange(tempId: string): { from: number; to: number } | null {
    if (!editor) return null;
    let range: { from: number; to: number } | null = null;
    editor.state.doc.descendants((node, pos) => {
      if (range) return false;
      if (node.type.name === "uploadPlaceholder" && node.attrs.tempId === tempId) {
        range = { from: pos, to: pos + node.nodeSize };
        return false;
      }
    });
    return range;
  }

  // Реальная жалоба: перетащил/выбрал файл — на холсте ничего не
  // появлялось, пока не завершится вся загрузка (передача по сети + ответ
  // сервера) — "не моментально, а с большой задержкой", хотя пользователь
  // ожидал увидеть что-то сразу, "чтобы выглядело отзывчиво". Теперь на
  // месте вставки СРАЗУ (ещё до begin запроса) появляется карточка
  // "Загружается…" (uploadPlaceholder), которая заменяется на настоящую
  // картинку/видео/аудио/документ по готовности — по tempId (см.
  // findPlaceholderRange выше), а на ошибке — на текст с предупреждением,
  // чтобы спиннер не остался висеть навсегда.
  //
  // Общая точка для всех трёх входов (кнопка «Картинка», кнопка «Файл»,
  // вставка из буфера/drag-and-drop) — insertUploadedFileAt сам разбирает
  // по content_type и вызывает insertImageAt для картинок, так что
  // отдельная ветка для картиночного пикера не нужна.
  //
  // Грузим и вставляем ПОСЛЕДОВАТЕЛЬНО (не Promise.all) — реальная жалоба:
  // с телефона нельзя было выбрать пачку файлов сразу, системный пикер
  // даёт выбрать несколько, но код брал только files[0]; порядок вставки в
  // заметке должен совпадать с порядком выбора, и один прогресс-бар на все
  // параллельные загрузки не имел бы смысла.
  async function uploadAndInsertFiles(files: File[], atPos?: number) {
    if (!files.length || !item) return;
    let pos: number | { from: number; to: number } = atPos ?? editor?.state.selection.to ?? 0;
    try {
      for (let i = 0; i < files.length; i++) {
        setUploadBatch({ current: i + 1, total: files.length });
        setUploadProgress(0);

        let tempId: string | null = null;
        if (mode === "wysiwyg" && editor) {
          tempId = crypto.randomUUID();
          editor
            .chain()
            .focus()
            .insertContentAt(pos, { type: "uploadPlaceholder", attrs: { tempId, filename: files[i].name } })
            .run();
          pos = editor.state.selection.to;
        }

        try {
          const uploaded = await uploadFile.mutateAsync({ file: files[i], onProgress: setUploadProgress });
          const range = tempId ? findPlaceholderRange(tempId) : null;
          pos = insertUploadedFileAt(range ?? pos, uploaded, files[i]);
        } catch (err) {
          const range = tempId ? findPlaceholderRange(tempId) : null;
          if (range && editor) {
            editor
              .chain()
              .focus()
              .insertContentAt(range, {
                type: "paragraph",
                content: [{ type: "text", text: `⚠️ Не удалось загрузить «${files[i].name}»` }],
              })
              .run();
            pos = editor.state.selection.to;
          }
          throw err;
        }
      }
    } finally {
      setUploadProgress(null);
      setUploadBatch(null);
    }
  }

  async function onPickImage(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    await uploadAndInsertFiles(files);
  }

  async function pasteFiles(files: File[], atPos?: number) {
    await uploadAndInsertFiles(files, atPos);
  }

  async function onPickFile(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    await uploadAndInsertFiles(files);
  }

  if (!item) {
    return <div className="flex h-full items-center justify-center text-subtle">Загрузка…</div>;
  }

  const availableTags = (allTags ?? []).filter((t) => !item.tags.some((it) => it.id === t.id));
  const filteredAvailableTags = availableTags.filter((t) =>
    t.name.toLowerCase().includes(tagQuery.trim().toLowerCase()),
  );
  const tagExactMatch = (allTags ?? []).some((t) => t.name.toLowerCase() === tagQuery.trim().toLowerCase());
  const showImageToolbar = mode === "wysiwyg" && !!editor?.isActive("image");
  const showVideoToolbar = mode === "wysiwyg" && !!editor?.isActive("video");
  const showCodeBlockToolbar = mode === "wysiwyg" && !!editor?.isActive("codeBlock");
  const showTableToolbar = mode === "wysiwyg" && !!editor?.isActive("table");

  const widthClass =
    contentWidth === "narrow" ? "mx-auto max-w-3xl" : contentWidth === "wide" ? "mx-auto max-w-5xl" : "max-w-none";

  function changeContentWidth(width: ContentWidth) {
    setContentWidth(width);
    uiStorage.setContentWidth(width);
  }

  async function handleExport(format: "md" | "html") {
    if (!item) return;
    const filename = sanitizeFilename(item.title);
    if (format === "md") {
      const markdown = editor?.storage.markdown.getMarkdown() ?? content;
      downloadFile(`${filename}.md`, await inlineImages(markdown), "text/markdown");
    } else {
      const html = editor?.getHTML() ?? "";
      const inlined = await inlineImages(html);
      downloadFile(`${filename}.html`, wrapHtmlDocument(item.title || "Без названия", inlined), "text/html");
    }
  }

  async function createAndAttachTag() {
    const name = tagQuery.trim();
    if (!name) return;
    const tag = await createTag.mutateAsync(name);
    addTag.mutate(tag.id);
    setTagQuery("");
    setShowTagPicker(false);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col border-b">
        {/* Ряд 1: заголовок — намеренно НЕ flex-wrap и без переменной по
            длине компании (теги раньше стояли прямо тут и при их количестве
            заголовок сжимался/переносился — жалоба в отзыве). Только
            фиксированные по ширине элементы делят с ним строку. */}
        <div className="flex items-center gap-2 p-3 pb-2">
          <button
            onClick={onBack}
            className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-subtle lg:hidden"
          >
            <ChevronLeft size={18} />
          </button>
          <div className="relative shrink-0">
            <button
              onClick={() => setShowEmojiPicker((v) => !v)}
              title="Иконка заметки"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded border text-lg hover:bg-muted-hover"
            >
              {item.icon || "🙂"}
            </button>
            {showEmojiPicker && (
              <Suspense
                fallback={
                  <div className="absolute z-20 mt-1 flex h-24 w-24 items-center justify-center rounded border bg-surface shadow-lg">
                    <Spinner size={20} />
                  </div>
                }
              >
                <EmojiPickerPopover
                  onSelect={(emoji) => updateItem.mutate({ id: item.id, icon: emoji })}
                  onClose={() => setShowEmojiPicker(false)}
                />
              </Suspense>
            )}
          </div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Без названия"
            style={item.color ? { color: item.color } : undefined}
            className="min-w-0 flex-1 text-lg font-semibold outline-none"
          />
          <div className="hidden shrink-0 items-center gap-1 md:flex">
            <span className="mr-1 flex items-center gap-1 whitespace-nowrap text-xs text-subtle">
              {(collabStatus === "connecting" || collabStatus === "stale") && (
                <>
                  <Spinner size={12} /> {collabStatus === "stale" ? "Обновляем…" : "Подключение…"}
                </>
              )}
              {collabStatus === "disconnected" && (
                <span className="flex items-center gap-1 text-warning" title="Нет связи — редактирование заблокировано">
                  <WifiOff size={12} /> Нет связи
                </span>
              )}
              {collabStatus === "connected" && (
                <span title="Совместное редактирование" className="flex items-center text-success">
                  <Users size={12} />
                </span>
              )}
              {updateAvailable ? (
                <span className="text-warning" title="Правки не сохраняются — обновите страницу (баннер сверху)">
                  Не сохраняется — обновите вкладку
                </span>
              ) : (
                <>
                  {!collabStatus && status === "saving" && <Spinner size={12} />}
                  {!collabStatus && (status === "saving" ? "Сохраняем…" : status === "saved" ? "Сохранено" : "")}
                </>
              )}
            </span>
            <div className="flex overflow-hidden rounded border">
              {(["view", "wysiwyg", "raw"] as const).map((m) => {
                const ModeIcon = MODE_ICON[m];
                return (
                  <button
                    key={m}
                    onClick={() => switchMode(m)}
                    title={MODE_LABEL[m]}
                    className={`flex h-8 w-8 items-center justify-center ${mode === m ? "bg-accent text-white" : "text-subtle hover:bg-muted-hover"}`}
                  >
                    <ModeIcon size={16} />
                  </button>
                );
              })}
            </div>
            <div className="relative">
              <button
                onClick={() => setShowColorPicker((v) => !v)}
                title="Цвет заголовка"
                className="flex h-8 w-8 items-center justify-center rounded border text-secondary hover:bg-muted-hover"
              >
                <Palette size={16} />
              </button>
              {showColorPicker && (
                <div className="absolute right-0 z-20 mt-1 flex w-40 flex-wrap gap-1 rounded border bg-surface p-2 shadow-lg">
                  <button
                    onClick={() => {
                      updateItem.mutate({ id: item.id, color: null });
                      setShowColorPicker(false);
                    }}
                    title="Без цвета"
                    className="h-6 w-6 rounded-full border text-xs text-subtle"
                  >
                    ×
                  </button>
                  {COLORS.map((c) => (
                    <button
                      key={c}
                      onClick={() => {
                        updateItem.mutate({ id: item.id, color: c });
                        setShowColorPicker(false);
                      }}
                      style={{ backgroundColor: c }}
                      className="h-6 w-6 rounded-full border"
                    />
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={() => updateItem.mutate({ id: item.id, pinned: !item.pinned })}
              title={item.pinned ? "Открепить" : "Закрепить как важное"}
              className={`flex h-8 w-8 items-center justify-center rounded border ${item.pinned ? "bg-accent text-white" : "text-secondary hover:bg-muted-hover"}`}
            >
              {item.pinned ? <PinOff size={16} /> : <Pin size={16} />}
            </button>
            {currentSpaceIsPublicPages && (
              <button
                onClick={() => setShowShareModal(true)}
                title="Публичная ссылка"
                className="flex h-8 w-8 items-center justify-center rounded border text-secondary hover:bg-muted-hover"
              >
                <Globe size={16} />
              </button>
            )}
            <button
              onClick={() => setShowHistory((v) => !v)}
              title="История версий"
              className="flex h-8 w-8 items-center justify-center rounded border text-secondary hover:bg-muted-hover"
            >
              <History size={16} />
            </button>
            <ExportMenu onExport={handleExport} />
            <button
              onClick={() => archiveItem.mutate(item.id)}
              disabled={archiveItem.isPending}
              title="В архив — убрать с глаз, не удаляя"
              className="flex h-8 w-8 items-center justify-center rounded border text-secondary hover:bg-muted-hover disabled:opacity-50"
            >
              {archiveItem.isPending ? <Spinner size={16} /> : <Archive size={16} />}
            </button>
            <button
              onClick={() => setConfirmingDelete(true)}
              disabled={deleteItem.isPending}
              title="Удалить заметку"
              className="flex h-8 w-8 items-center justify-center rounded border text-danger hover:bg-danger/10 disabled:opacity-50"
            >
              {deleteItem.isPending ? <Spinner size={16} /> : <Trash2 size={16} />}
            </button>
          </div>
          <button
            ref={mobileActionsButtonRef}
            onClick={() => setShowMobileActions((v) => !v)}
            title="Действия с заметкой"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded border text-secondary hover:bg-muted-hover md:hidden"
          >
            <MoreVertical size={16} />
          </button>
        </div>

        {showMobileActions && (
          <MobileNoteActionsMenu
            triggerRef={mobileActionsButtonRef}
            item={item}
            mode={mode}
            switchMode={switchMode}
            updateItem={updateItem}
            showColorPicker={showColorPicker}
            setShowColorPicker={setShowColorPicker}
            currentSpaceIsPublicPages={currentSpaceIsPublicPages}
            setShowShareModal={setShowShareModal}
            setShowHistory={setShowHistory}
            handleExport={handleExport}
            archiveItem={archiveItem}
            setConfirmingDelete={setConfirmingDelete}
            deleteItem={deleteItem}
            onClose={() => setShowMobileActions(false)}
          />
        )}

        {/* Ряд 2: папка + теги — здесь можно и перенестись на новую строку,
            заголовок сверху уже не задет. Теги свёрнуты в выпадающий список
            (как папка — <select>), а не показаны все чипами сразу — та же
            причина. */}
        <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
          <select
            value={item.folder_id ?? ""}
            onChange={(e) => updateItem.mutate({ id: item.id, folder_id: e.target.value || null })}
            className="rounded border px-1.5 py-1 text-xs text-secondary"
          >
            <option value="">Без папки</option>
            {(folders ?? []).map((folder) => (
              <option key={folder.id} value={folder.id}>
                {folder.name}
              </option>
            ))}
          </select>

          {/* Перенос ИЗ сейфа обычным move не поддерживается (нужна расшифровка
              на клиенте перед сохранением plaintext — вне скоупа) — кнопку
              для сейфовой заметки прячем целиком. Перенос В сейф — поддержан
              (migrateItemToVault ниже, шифрует перед move), но только для
              заметок (не списков/билетов) и только в УЖЕ разблокированный
              сейф — просить пароль сейфа посреди переноса не делаем, сейф
              нужно открыть заранее в сайдбаре. */}
          {!isVaultNote && (
            <button
              onClick={() => setShowMoveModal(true)}
              title="Переместить в другой спейс или папку"
              className="rounded border px-1.5 py-1 text-xs text-secondary hover:bg-muted-hover"
            >
              Переместить…
            </button>
          )}

          <div className="relative">
            <button
              onClick={() => {
                setShowTagPicker((v) => !v);
                setTagQuery("");
              }}
              className="flex items-center gap-1 rounded-full border border-dashed px-2 py-0.5 text-xs text-subtle hover:text-secondary"
            >
              <TagIcon size={12} />
              {item.tags.length > 0 ? `Теги (${item.tags.length})` : "+ тег"}
            </button>
            {showTagPicker && (
              <div className="absolute z-10 mt-1 w-56 rounded border bg-surface p-1 shadow-lg">
                {item.tags.length > 0 && (
                  <div className="mb-1 flex flex-wrap gap-1 border-b p-1 pb-2">
                    {item.tags.map((tag) => (
                      <span
                        key={tag.id}
                        title={tag.auto ? "Автоматически предложенный тег" : undefined}
                        className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
                          tag.auto
                            ? "border border-dashed border-brand/40 bg-brand/10 text-brand"
                            : "bg-muted-hover text-secondary"
                        }`}
                      >
                        {tag.auto && <Sparkles size={10} />}
                        #{tag.name}
                        <button onClick={() => removeTag.mutate(tag.id)} className="text-subtle hover:text-danger">
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <input
                  autoFocus
                  value={tagQuery}
                  onChange={(e) => setTagQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !tagExactMatch && tagQuery.trim()) createAndAttachTag();
                  }}
                  placeholder="Найти или создать тег"
                  className="mb-1 w-full rounded border px-2 py-1 text-xs outline-none"
                />
                <div className="max-h-40 overflow-y-auto">
                  {filteredAvailableTags.map((tag) => (
                    <button
                      key={tag.id}
                      onClick={() => {
                        addTag.mutate(tag.id);
                        setShowTagPicker(false);
                      }}
                      className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-muted-hover"
                    >
                      #{tag.name}
                    </button>
                  ))}
                  {tagQuery.trim() && !tagExactMatch && (
                    <button
                      onClick={createAndAttachTag}
                      disabled={createTag.isPending}
                      className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs text-secondary hover:bg-muted-hover disabled:opacity-50"
                    >
                      {createTag.isPending && <Spinner size={12} />}
                      Создать «{tagQuery.trim()}»
                    </button>
                  )}
                  {filteredAvailableTags.length === 0 && !tagQuery.trim() && (
                    <div className="px-2 py-1 text-xs text-subtle">Нет доступных тегов</div>
                  )}
                </div>
              </div>
            )}
          </div>

          <button
            onClick={() => suggestTags.mutate()}
            disabled={suggestTags.isPending}
            title="Предложить теги по содержимому заметки"
            className="flex items-center gap-1 rounded-full border border-dashed px-2 py-0.5 text-xs text-brand hover:text-brand disabled:opacity-50"
          >
            {suggestTags.isPending ? <Spinner size={12} /> : <Sparkles size={12} />}
            Предложить теги
          </button>
        </div>

        {/* Бэклинки (ТЗ §7) — заметки, ссылающиеся НА эту через [[название.
            Показываем только когда есть что показывать — пустая строка
            "упоминается в 0 заметках" никому не нужна. */}
        {(backlinks ?? []).length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-t px-3 py-2 text-xs text-subtle">
            <span className="shrink-0">Упоминается в {backlinks!.length} {backlinks!.length === 1 ? "заметке" : "заметках"}:</span>
            {backlinks!.map((b) => (
              <button
                key={b.id}
                onClick={() => onOpenItemRef.current?.(b.id)}
                className="flex items-center gap-1 rounded bg-muted-hover px-1.5 py-0.5 text-secondary hover:bg-muted-active"
              >
                <FileText size={11} className="shrink-0 text-subtle" />
                {b.title || "Без названия"}
              </button>
            ))}
          </div>
        )}
      </div>

      <input ref={imageInputRef} type="file" accept="image/*" multiple hidden onChange={onPickImage} />
      <input ref={fileInputRef} type="file" multiple hidden onChange={onPickFile} />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {mode !== "raw" && (
          <EditorToolbar
            editor={editor}
            onInsertImage={() => imageInputRef.current?.click()}
            onInsertFile={() => fileInputRef.current?.click()}
            onOpenRecorder={isVaultNote ? undefined : openRecorder}
            onInsertTable={
              isVaultNote
                ? undefined
                : () => {
                    if (!editor) return;
                    setInsertTablePos(editor.state.selection.from);
                    setInsertTableModalOpen(true);
                  }
            }
            uploadProgress={uploadProgress}
            uploadBatch={uploadBatch}
            contentWidth={contentWidth}
            onContentWidthChange={changeContentWidth}
            onAiAction={applyAiAction}
            onOpenAssistant={openAssistant}
            aiLoading={aiLoading}
            readOnly={mode === "view"}
            showToc={showToc}
            onToggleToc={() => setShowToc((v) => !v)}
          />
        )}
        {aiError && (
          <div className="border-b bg-danger/10 px-3 py-1.5 text-xs text-danger">{aiError}</div>
        )}
        {showImageToolbar && editor && <ImageToolbar editor={editor} />}
        {showVideoToolbar && editor && <VideoToolbar editor={editor} />}
        {showCodeBlockToolbar && editor && <CodeBlockToolbar editor={editor} />}
        {showTableToolbar && editor && <TableToolbar editor={editor} />}
        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <div
            // pb-[50vh] (не только в raw — там своя textarea с обычным
            // поведением) — реальная просьба: хочется докрутить скролл ниже
            // конца документа, чтобы при желании держать последнюю строку
            // по центру экрана, а не прилипшей к низу окна.
            className={`relative min-h-0 flex-1 overflow-y-auto p-4 ${mode !== "raw" ? "pb-[50vh]" : ""}`}
            onMouseDown={(e) => {
              // Реальный найденный баг: EditorContent рендерит собственную
              // обёртку с классом .tiptap, а ВНУТРИ неё — настоящий
              // редактируемый узел ProseMirror (тоже .tiptap, плюс
              // .ProseMirror). min-height:100% из index.css применяется к
              // обоим, но у вложенного узла процентная высота не резолвится
              // в реальную высоту флекс-контейнера (нет явно заданного
              // height у родителя — только flex-grow) — вложенный
              // ProseMirror-узел оказывается высотой ровно с контент (для
              // пустой заметки — одна строка), а не на всю видимую область.
              // Клик куда угодно НИЖЕ этой полоски попадает на пустую
              // обёртку и никогда не доходит до самого редактора — "ничего
              // не печатается", хотя визуально место выглядит как часть
              // заметки. Не чиним саму геометрию (пришлось бы перекраивать
              // всю цепочку flex/скролла), а как в любом блочном редакторе
              // (Notion, Linear и т.п.) — клик мимо текста ставит курсор в
              // конец документа.
              //
              // Реальный найденный регресс от этого же фикса: BubbleMenu
              // (кнопка «ИИ» / «Спросить ассистента» при выделении текста)
              // через tippy.js по умолчанию (appendTo: 'parent') вставляется
              // ребёнком именно этого контейнера, а не внутрь editor.view.dom.
              // Без этой проверки клик по кнопке ИИ схлопывал выделение
              // ДО того, как успевал сработать сам клик — BubbleMenu
              // реагирует на пустое выделение и тут же прячется. Пока
              // выделение не пустое, ничего не трогаем — такой клик почти
              // наверняка по всплывающей панели, а не мимо текста.
              if (mode !== "wysiwyg" || !editor) return;
              if (!editor.state.selection.empty) return;
              if (editor.view.dom.contains(e.target as Node)) return;
              e.preventDefault();
              editor.commands.focus("end");
            }}
          >
            {/* EditorContent/BubbleMenu держат собственный DOM в обход React
                (ProseMirror-вью и tippy.js-попап у BubbleMenu) — полное
                размонтирование этой ветки при переключении режима (было:
                тернарник) роняло React с "Failed to execute 'removeChild'"
                и белым экраном без ErrorBoundary. Теперь ветка всегда
                смонтирована, режим переключается через CSS, а не через
                unmount. */}
            {editor && (
              <BubbleMenu editor={editor} shouldShow={({ state }) => mode === "wysiwyg" && !state.selection.empty}>
                <div className="rounded border bg-surface shadow-lg">
                  <AiMenu onAction={applyAiAction} onOpenAssistant={openAssistant} loading={aiLoading} />
                </div>
              </BubbleMenu>
            )}
            {(collabStatus === "connecting" || collabStatus === "stale") && (
              // Реальная жалоба: рестарт backend'а (деплой) рвёт живую
              // коллаборацию у всех открытых заметок разом — пока клиент
              // переподключается, редактор показывал ЧТО ЕСТЬ ПРЯМО СЕЙЧАС
              // (иногда пусто на переходный момент), без разницы "ещё
              // грузится" vs "и правда пусто" — выглядело как потеря
              // контента. Непрозрачная плашка поверх (не просто спиннер в
              // углу статуса, как раньше) однозначно говорит "подожди",
              // пока идёт reconnect+refetch (см. эффект выше на collabStatus
              // === "stale"/"disconnected").
              <div className="absolute inset-0 z-10 space-y-3 bg-surface p-4">
                <div className="h-4 w-4/5 animate-pulse rounded bg-muted-active" />
                <div className="h-4 w-full animate-pulse rounded bg-muted-active" />
                <div className="h-4 w-11/12 animate-pulse rounded bg-muted-active" />
                <div className="h-4 w-3/5 animate-pulse rounded bg-muted-active" />
              </div>
            )}
            <EditorContent
              editor={editor}
              className={`tiptap ${widthClass} ${mode === "raw" ? "hidden" : ""}`}
            />
            {mode === "raw" && (
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                className="h-full w-full resize-none font-mono text-sm outline-none"
                placeholder="Текст в Markdown…"
              />
            )}
          </div>
          {showToc && mode !== "raw" && <TableOfContentsPanel editor={editor} onClose={() => setShowToc(false)} />}
          {showHistory && <VersionHistoryPanel itemId={item.id} onClose={() => setShowHistory(false)} />}
          {showShareModal && <ShareNoteModal itemId={item.id} onClose={() => setShowShareModal(false)} />}
        </div>
      </div>

      {confirmingDelete && (
        <ConfirmDialog
          title="Удалить заметку?"
          danger
          onConfirm={async () => {
            setConfirmingDelete(false);
            await deleteItem.mutateAsync(item.id);
            onDeleted();
          }}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}

      {pendingSpaceId &&
        (() => {
          // Единственный оставшийся producer pendingSpaceId — выбор
          // сейф-спейса в MoveItemModal (onSelectVaultSpace ниже): обычный
          // перенос в другой спейс/папку теперь идёт напрямую через
          // moveItemSpace, без промежуточного confirm-диалога.
          const targetSpace = (spaces ?? []).find((s) => s.id === pendingSpaceId);
          return (
            <ConfirmDialog
              title={`Перенести заметку в сейф «${targetSpace?.name ?? ""}»? Текст и вложенные файлы будут зашифрованы, папка сбросится.`}
              confirmLabel="Перенести"
              onConfirm={async () => {
                const spaceId = pendingSpaceId;
                setPendingSpaceId(null);
                // Миграция шифрует item.content с сервера, не live-состояние
                // редактора — несохранённые правки потерялись бы, а
                // следующий автосейв мог бы затереть уже зашифрованную
                // заметку обратно plaintext'ом. Сначала досохраняем.
                if (title !== savedRef.current.title || content !== savedRef.current.content) {
                  await updateItem.mutateAsync({ id: item.id, title, content });
                  savedRef.current = { title, content };
                }
                await migrateItemToVault.mutateAsync({ item: { ...item, title, content }, targetSpaceId: spaceId });
              }}
              onCancel={() => setPendingSpaceId(null)}
            />
          );
        })()}

      {showMoveModal && (
        <MoveItemModal
          spaces={(spaces ?? []).filter(
            (s) => !s.is_vault || (item.material_type === "note" && getVaultKey(s.id))
          )}
          currentSpaceId={item.space_id}
          currentFolderId={item.folder_id}
          onSelectVaultSpace={(spaceId) => {
            setShowMoveModal(false);
            setPendingSpaceId(spaceId);
          }}
          onMove={(spaceId, folderId) => {
            setShowMoveModal(false);
            moveItemSpace.mutate({ id: item.id, space_id: spaceId, folder_id: folderId });
          }}
          onClose={() => setShowMoveModal(false)}
        />
      )}

      {reminderModalOpen && (
        <ReminderModal
          defaultTitle={item.title}
          onCreate={({ title: t, body, triggerAt }) => {
            setReminderModalOpen(false);
            const anchorPos = reminderAnchorPos;
            createReminder.mutate(
              { title: t, body, trigger_at: triggerAt.toISOString(), item_id: item.id },
              {
                onSuccess: (notification) => {
                  // Якорь вставляется ПОСЛЕ успешного создания, не сразу
                  // при открытии формы — если пользователь отменит или
                  // запрос упадёт, лишней иконки в заметке остаться не
                  // должно (реальная жалоба была ровно про обратное:
                  // "не сохранилось" — но раз уж чиним, сразу без риска
                  // рассинхрона с тем, что реально создалось на бэкенде).
                  if (editor && anchorPos !== null) {
                    editor
                      .chain()
                      .insertContentAt(anchorPos, {
                        type: "reminderAnchor",
                        attrs: { notificationId: notification.id, title: t },
                      })
                      .run();
                  }
                },
              },
            );
          }}
          onCancel={() => setReminderModalOpen(false)}
        />
      )}

      {insertTableModalOpen && (
        <InsertTableModal
          spaceId={item.space_id}
          folderId={item.folder_id}
          onInsert={(tableId) => {
            setInsertTableModalOpen(false);
            const pos = insertTablePos;
            if (editor && pos !== null) {
              editor
                .chain()
                .insertContentAt(pos, [{ type: "tableEmbed", attrs: { tableId } }, { type: "paragraph" }])
                .run();
            }
          }}
          onCancel={() => setInsertTableModalOpen(false)}
        />
      )}

      {assistantModalOpen && (
        <NoteAssistantModal
          itemId={item.id}
          selectionText={assistantSelectionText}
          onApply={applyFromAssistant}
          onClose={() => setAssistantModalOpen(false)}
        />
      )}

      {recordingPanelOpen && (
        <RecordingPanel
          spaceId={item.space_id}
          onStarted={onRecordingStarted}
          onClose={() => setRecordingPanelOpen(false)}
        />
      )}
    </div>
  );
}
