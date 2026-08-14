import { useEditor, EditorContent, BubbleMenu } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import LinkExtension from "@tiptap/extension-link";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import { createLowlight, common } from "lowlight";
import { Markdown } from "tiptap-markdown";
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { ChevronLeft, Code2, Eye, History, Palette, Pin, PinOff, Sparkles, Tag as TagIcon, Trash2 } from "lucide-react";
import { uiStorage, type ContentWidth } from "../lib/storage";
import { downloadFile, inlineImages, sanitizeFilename, wrapHtmlDocument } from "../lib/export";
import {
  useAddItemTag,
  useAiTransform,
  useCreateReminder,
  useCreateTag,
  useDeleteItem,
  useFolders,
  useItem,
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
import CodeBlockToolbar from "./CodeBlockToolbar";
import TableToolbar from "./TableToolbar";
import Spinner from "./Spinner";
import ConfirmDialog from "./ConfirmDialog";
import ReminderModal from "./ReminderModal";
import NoteAssistantModal from "./NoteAssistantModal";
import RecordingPanel from "./RecordingPanel";
import ExportMenu from "./ExportMenu";
import { ResizableImage } from "../extensions/ResizableImage";
import { Video } from "../extensions/Video";
import { Audio } from "../extensions/Audio";
import { LinkPreview } from "../extensions/LinkPreview";
import { DocumentAttachment, serializeDocumentAttachment } from "../extensions/DocumentAttachment";
import { TicketAttachment } from "../extensions/TicketAttachment";
import { Spacer } from "../extensions/Spacer";
import { ProcessingPlaceholder } from "../extensions/ProcessingPlaceholder";
import { InlineLinkFavicon } from "../extensions/InlineLinkFavicon";
import { DataRecognition } from "../extensions/DataRecognition";
import { ReminderAnchor } from "../extensions/ReminderAnchor";
import { ImageOcrResult } from "../extensions/ImageOcrResult";
import { SlashCommand } from "../extensions/SlashCommand";

// Только когда вставленный текст ЦЕЛИКОМ — голая ссылка (случай "вставил
// ссылку на сайт, чтобы сохранить на потом" — реальный сценарий из
// отзыва). Ссылки внутри обычного текста остаются обычными подчёркнутыми
// ссылками — превращать их в карточки было бы избыточно и ломало бы поток
// чтения.
const BARE_URL_RE = /^https?:\/\/\S+$/;

const EmojiPickerPopover = lazy(() => import("./EmojiPickerPopover"));
const lowlight = createLowlight(common);

type Mode = "wysiwyg" | "raw";

const COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#a855f7", "#ec4899"];

export default function NoteEditor({
  itemId,
  onDeleted,
  onBack,
  highlightAnchorId,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
  // Переход из напоминания, поставленного якорем на конкретную строку
  // (см. ReminderAnchor.ts) — прокрутить и подсветить, тот же приём, что
  // highlightEntryId у ListEditor.tsx.
  highlightAnchorId?: string | null;
}) {
  const { data: item, isError } = useItem(itemId);
  const updateItem = useUpdateItem();
  const deleteItem = useDeleteItem(item?.space_id);
  const uploadFile = useUploadFile(item?.space_id);
  const { data: allTags } = useTags();
  const addTag = useAddItemTag(itemId);
  const removeTag = useRemoveItemTag(itemId);
  const suggestTags = useSuggestTags(itemId);
  const createTag = useCreateTag();
  const { data: folders } = useFolders(item?.space_id);
  const { data: spaces } = useSpaces();
  const moveItemSpace = useMoveItemSpace();
  const aiTransform = useAiTransform();
  const createReminder = useCreateReminder();

  const [mode, setMode] = useState<Mode>("wysiwyg");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [showHistory, setShowHistory] = useState(false);
  const [showTagPicker, setShowTagPicker] = useState(false);
  const [tagQuery, setTagQuery] = useState("");
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [pendingSpaceId, setPendingSpaceId] = useState<string | null>(null);
  const [showColorPicker, setShowColorPicker] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [reminderModalOpen, setReminderModalOpen] = useState(false);
  const [reminderAnchorPos, setReminderAnchorPos] = useState<number | null>(null);
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

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ codeBlock: false }),
      CodeBlockLowlight.configure({ lowlight }),
      ResizableImage,
      Video,
      Audio,
      LinkPreview,
      DocumentAttachment,
      TicketAttachment,
      Spacer,
      ProcessingPlaceholder,
      InlineLinkFavicon,
      DataRecognition,
      ReminderAnchor,
      ImageOcrResult,
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
      }),
    ],
    content: "",
    // Прямой editorProps.handlePaste, а не addPasteRules() у самого узла:
    // у tiptap-markdown включён transformPastedText, который перехватывает
    // вставку текста своим собственным handlePaste ДО обычного механизма
    // paste rules — если положиться на paste rules, превращение ссылки в
    // карточку могло бы вообще не сработать в зависимости от порядка
    // плагинов. editorProps на самом EditorView вызывается раньше любых
    // плагинных handlePaste, так что порядок гарантирован.
    editorProps: {
      handlePaste: (view, event) => {
        if (event.clipboardData?.files?.length) return false;
        const text = event.clipboardData?.getData("text/plain")?.trim();
        if (!text || !BARE_URL_RE.test(text)) return false;
        const { state } = view;
        const node = state.schema.nodes.linkPreview.create({ url: text });
        view.dispatch(state.tr.replaceSelectionWith(node));
        return true;
      },
    },
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

  // Заметку сменили — подгружаем её состояние в редактор заново.
  useEffect(() => {
    if (!item) return;
    setTitle(item.title);
    setContent(item.content);
    savedRef.current = { title: item.title, content: item.content };
    editor?.commands.setContent(item.content || "");
    setStatus("idle");
    loadedItemIdRef.current = item.id;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id]);

  // TicketAttachmentCard.tsx читает это при клике "Напомнить" — см.
  // комментарий в TicketAttachment.ts про то, почему storage, а не проп.
  useEffect(() => {
    if (!editor) return;
    editor.storage.ticketAttachment.itemId = item?.id ?? null;
    editor.storage.ticketAttachment.spaceId = item?.space_id ?? null;
  }, [editor, item?.id, item?.space_id]);

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
  useEffect(() => {
    if (!item || item.id !== loadedItemIdRef.current) return;
    if (item.content === savedRef.current.content) return;
    const hasPendingLocalEdit = content !== savedRef.current.content || title !== savedRef.current.title;
    if (hasPendingLocalEdit) return;
    setContent(item.content);
    savedRef.current = { ...savedRef.current, content: item.content };
    editor?.commands.setContent(item.content || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.content]);

  // Автосохранение с дебаунсом. Каждое изменение title/content создаёт
  // на бэкенде запись в item_versions — поэтому не сохраняем на каждый
  // символ, а ждём паузы в наборе.
  useEffect(() => {
    if (!item) return;
    if (title === savedRef.current.title && content === savedRef.current.content) {
      pendingRef.current = null;
      return;
    }
    pendingRef.current = { id: item.id, title, content };
    setStatus("saving");
    const timer = setTimeout(() => {
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
      if (pending) {
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
    } else {
      editor.commands.setContent(content || "");
    }
    setMode(next);
  }

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

  // Одна загруженная картинка — общий путь для обеих кнопок («Картинка» И
  // «Файл»): реальная жалоба — картинка, выбранная через «Файл» (обычный
  // системный пикер на телефоне не отличает кнопки), раньше попадала в
  // generic documentAttachment-карточку вместо изображения. Бэкенд всё
  // равно ставил vision-OCR в очередь (content_type определяется по
  // самому файлу, не по кнопке) — а плейсхолдер, на который воркер должен
  // заменить готовый результат, никогда не вставлялся, поэтому результат
  // молча терялся (_replace_in_referencing_items не находил, куда
  // вписать). Единая функция закрывает оба входа сразу.
  function insertImage(uploaded: { id: string; url: string }) {
    // Плейсхолдер — точная строка, которую backend ищет и заменяет на
    // готовое описание/OCR (app/vision.py, placeholder_text()); должна
    // совпадать 1:1, тот же приём, что и у видео-расшифровки.
    const placeholder = `⏳ Описание изображения ${uploaded.id} обрабатывается…`;
    if (mode === "wysiwyg" && editor) {
      editor
        .chain()
        .focus()
        .setImage({ src: uploaded.url })
        .insertContent({ type: "paragraph", content: [{ type: "text", text: placeholder }] })
        .run();
    } else {
      setContent((c) => `${c}\n\n![](${uploaded.url})\n\n${placeholder}\n`);
    }
  }

  function insertUploadedFile(uploaded: {
    id: string;
    url: string;
    filename: string;
    content_type: string;
    pdf_text: string | null;
    pdf_ocr_queued: boolean;
    preview_text: string | null;
  }) {
    if (uploaded.content_type.startsWith("image/")) {
      insertImage(uploaded);
      return;
    }
    const isVideo = uploaded.content_type.startsWith("video/");
    const isAudio = uploaded.content_type.startsWith("audio/");
    // Плейсхолдер — точная строка, которую backend ищет и заменяет на
    // готовый результат (app/transcription.py и app/pdf_processing.py,
    // placeholder_text()) — держать в одном месте на фронте не
    // получится, но текст должен совпадать 1:1, иначе замена не найдёт,
    // куда вписать результат.
    const placeholder = `⏳ Расшифровка ${uploaded.id} обрабатывается…`;
    const pdfPlaceholder = `⏳ Распознавание PDF ${uploaded.id} обрабатывается…`;
    // Аудио — сразу готовый плеер, без плейсхолдера: расшифровка для
    // отдельно загруженных аудиофайлов не подключена (только для видео),
    // плеер сам по себе и есть превью, ждать нечего.
    const previewText = uploaded.pdf_text ?? uploaded.preview_text ?? "";
    if (mode === "wysiwyg" && editor) {
      if (isVideo) {
        editor
          .chain()
          .focus()
          .insertContent({ type: "video", attrs: { src: uploaded.url, filename: uploaded.filename } })
          .insertContent({ type: "paragraph", content: [{ type: "text", text: placeholder }] })
          .run();
      } else if (isAudio) {
        editor
          .chain()
          .focus()
          .insertContent({ type: "audio", attrs: { src: uploaded.url, filename: uploaded.filename } })
          .run();
      } else if (uploaded.pdf_ocr_queued) {
        // Авто-OCR уже поставлен в очередь на бэкенде — плейсхолдер, не
        // карточка сразу: backend заменит его целиком на готовую
        // карточку с текстом, когда распознавание закончится.
        editor
          .chain()
          .focus()
          .insertContent({ type: "paragraph", content: [{ type: "text", text: pdfPlaceholder }] })
          .run();
      } else {
        editor
          .chain()
          .focus()
          .insertContent({
            type: "documentAttachment",
            attrs: { url: uploaded.url, filename: uploaded.filename, text: previewText },
          })
          .run();
      }
    } else if (isVideo) {
      setContent(
        (c) =>
          `${c}\n\n<video src="${uploaded.url}" controls preload="metadata" style="max-width: 100%; max-height: 70vh;"></video>\n\n${placeholder}\n`,
      );
    } else if (isAudio) {
      setContent(
        (c) => `${c}\n\n<audio src="${uploaded.url}" controls preload="metadata" style="max-width: 100%;"></audio>\n`,
      );
    } else if (uploaded.pdf_ocr_queued) {
      setContent((c) => `${c}\n\n${pdfPlaceholder}\n`);
    } else {
      setContent((c) => `${c}\n\n${serializeDocumentAttachment(uploaded.url, uploaded.filename, previewText)}\n`);
    }
  }

  // Реальная жалоба: с телефона нельзя было выбрать пачку файлов сразу —
  // системный пикер даёт выбрать несколько, инпут их принимал бы, но
  // код брал только files[0]. Грузим и вставляем ПОСЛЕДОВАТЕЛЬНО (не
  // Promise.all): порядок вставки в заметке должен совпадать с порядком
  // выбора, и один прогресс-бар на все параллельные загрузки не имел бы
  // смысла.
  async function onPickImage(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length || !item) return;
    try {
      for (let i = 0; i < files.length; i++) {
        setUploadBatch({ current: i + 1, total: files.length });
        setUploadProgress(0);
        const uploaded = await uploadFile.mutateAsync({ file: files[i], onProgress: setUploadProgress });
        insertImage(uploaded);
      }
    } finally {
      setUploadProgress(null);
      setUploadBatch(null);
    }
  }

  async function onPickFile(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length || !item) return;
    try {
      for (let i = 0; i < files.length; i++) {
        setUploadBatch({ current: i + 1, total: files.length });
        setUploadProgress(0);
        const uploaded = await uploadFile.mutateAsync({ file: files[i], onProgress: setUploadProgress });
        insertUploadedFile(uploaded);
      }
    } finally {
      setUploadProgress(null);
      setUploadBatch(null);
    }
  }

  if (!item) {
    return <div className="flex h-full items-center justify-center text-slate-400">Загрузка…</div>;
  }

  const availableTags = (allTags ?? []).filter((t) => !item.tags.some((it) => it.id === t.id));
  const filteredAvailableTags = availableTags.filter((t) =>
    t.name.toLowerCase().includes(tagQuery.trim().toLowerCase()),
  );
  const tagExactMatch = (allTags ?? []).some((t) => t.name.toLowerCase() === tagQuery.trim().toLowerCase());
  const showImageToolbar = mode === "wysiwyg" && !!editor?.isActive("image");
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
            className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 lg:hidden"
          >
            <ChevronLeft size={18} />
          </button>
          <div className="relative shrink-0">
            <button
              onClick={() => setShowEmojiPicker((v) => !v)}
              title="Иконка заметки"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded border text-lg hover:bg-slate-50"
            >
              {item.icon || "🙂"}
            </button>
            {showEmojiPicker && (
              <Suspense
                fallback={
                  <div className="absolute z-20 mt-1 flex h-24 w-24 items-center justify-center rounded border bg-white shadow-lg">
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
          <div className="flex shrink-0 items-center gap-1">
            <span className="mr-1 flex w-20 items-center gap-1 text-xs text-slate-400">
              {status === "saving" && <Spinner size={12} />}
              {status === "saving" ? "Сохраняем…" : status === "saved" ? "Сохранено" : ""}
            </span>
            <div className="flex overflow-hidden rounded border">
              <button
                onClick={() => switchMode("wysiwyg")}
                title="WYSIWYG"
                className={`flex h-8 w-8 items-center justify-center ${mode === "wysiwyg" ? "bg-slate-900 text-white" : "text-slate-500 hover:bg-slate-50"}`}
              >
                <Eye size={16} />
              </button>
              <button
                onClick={() => switchMode("raw")}
                title="Markdown"
                className={`flex h-8 w-8 items-center justify-center ${mode === "raw" ? "bg-slate-900 text-white" : "text-slate-500 hover:bg-slate-50"}`}
              >
                <Code2 size={16} />
              </button>
            </div>
            <div className="relative">
              <button
                onClick={() => setShowColorPicker((v) => !v)}
                title="Цвет заголовка"
                className="flex h-8 w-8 items-center justify-center rounded border text-slate-600 hover:bg-slate-50"
              >
                <Palette size={16} />
              </button>
              {showColorPicker && (
                <div className="absolute right-0 z-20 mt-1 flex w-40 flex-wrap gap-1 rounded border bg-white p-2 shadow-lg">
                  <button
                    onClick={() => {
                      updateItem.mutate({ id: item.id, color: null });
                      setShowColorPicker(false);
                    }}
                    title="Без цвета"
                    className="h-6 w-6 rounded-full border text-xs text-slate-400"
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
              className={`flex h-8 w-8 items-center justify-center rounded border ${item.pinned ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            >
              {item.pinned ? <PinOff size={16} /> : <Pin size={16} />}
            </button>
            <button
              onClick={() => setShowHistory((v) => !v)}
              title="История версий"
              className="flex h-8 w-8 items-center justify-center rounded border text-slate-600 hover:bg-slate-50"
            >
              <History size={16} />
            </button>
            <ExportMenu onExport={handleExport} />
            <button
              onClick={() => setConfirmingDelete(true)}
              disabled={deleteItem.isPending}
              title="Удалить заметку"
              className="flex h-8 w-8 items-center justify-center rounded border text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              {deleteItem.isPending ? <Spinner size={16} /> : <Trash2 size={16} />}
            </button>
          </div>
        </div>

        {/* Ряд 2: папка + теги — здесь можно и перенестись на новую строку,
            заголовок сверху уже не задет. Теги свёрнуты в выпадающий список
            (как папка — <select>), а не показаны все чипами сразу — та же
            причина. */}
        <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
          <select
            value={item.folder_id ?? ""}
            onChange={(e) => updateItem.mutate({ id: item.id, folder_id: e.target.value || null })}
            className="rounded border px-1.5 py-1 text-xs text-slate-600"
          >
            <option value="">Без папки</option>
            {(folders ?? []).map((folder) => (
              <option key={folder.id} value={folder.id}>
                {folder.name}
              </option>
            ))}
          </select>

          {(spaces ?? []).length > 1 && (
            <select
              value={item.space_id}
              onChange={(e) => {
                if (e.target.value !== item.space_id) setPendingSpaceId(e.target.value);
              }}
              title="Перенести в другой спейс"
              className="rounded border px-1.5 py-1 text-xs text-slate-600"
            >
              {(spaces ?? []).map((space) => (
                <option key={space.id} value={space.id}>
                  {space.name}
                </option>
              ))}
            </select>
          )}

          <div className="relative">
            <button
              onClick={() => {
                setShowTagPicker((v) => !v);
                setTagQuery("");
              }}
              className="flex items-center gap-1 rounded-full border border-dashed px-2 py-0.5 text-xs text-slate-500 hover:text-slate-700"
            >
              <TagIcon size={12} />
              {item.tags.length > 0 ? `Теги (${item.tags.length})` : "+ тег"}
            </button>
            {showTagPicker && (
              <div className="absolute z-10 mt-1 w-56 rounded border bg-white p-1 shadow-lg">
                {item.tags.length > 0 && (
                  <div className="mb-1 flex flex-wrap gap-1 border-b p-1 pb-2">
                    {item.tags.map((tag) => (
                      <span
                        key={tag.id}
                        title={tag.auto ? "Автоматически предложенный тег" : undefined}
                        className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
                          tag.auto
                            ? "border border-dashed border-violet-300 bg-violet-50 text-violet-700"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {tag.auto && <Sparkles size={10} />}
                        #{tag.name}
                        <button onClick={() => removeTag.mutate(tag.id)} className="text-slate-400 hover:text-red-600">
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
                      className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-slate-100"
                    >
                      #{tag.name}
                    </button>
                  ))}
                  {tagQuery.trim() && !tagExactMatch && (
                    <button
                      onClick={createAndAttachTag}
                      disabled={createTag.isPending}
                      className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50"
                    >
                      {createTag.isPending && <Spinner size={12} />}
                      Создать «{tagQuery.trim()}»
                    </button>
                  )}
                  {filteredAvailableTags.length === 0 && !tagQuery.trim() && (
                    <div className="px-2 py-1 text-xs text-slate-400">Нет доступных тегов</div>
                  )}
                </div>
              </div>
            )}
          </div>

          <button
            onClick={() => suggestTags.mutate()}
            disabled={suggestTags.isPending}
            title="Предложить теги по содержимому заметки"
            className="flex items-center gap-1 rounded-full border border-dashed px-2 py-0.5 text-xs text-violet-500 hover:text-violet-700 disabled:opacity-50"
          >
            {suggestTags.isPending ? <Spinner size={12} /> : <Sparkles size={12} />}
            Предложить теги
          </button>
        </div>
      </div>

      <input ref={imageInputRef} type="file" accept="image/*" multiple hidden onChange={onPickImage} />
      <input ref={fileInputRef} type="file" multiple hidden onChange={onPickFile} />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {mode === "wysiwyg" && (
          <EditorToolbar
            editor={editor}
            onInsertImage={() => imageInputRef.current?.click()}
            onInsertFile={() => fileInputRef.current?.click()}
            onOpenRecorder={openRecorder}
            uploadProgress={uploadProgress}
            uploadBatch={uploadBatch}
            contentWidth={contentWidth}
            onContentWidthChange={changeContentWidth}
            onAiAction={applyAiAction}
            onOpenAssistant={openAssistant}
            aiLoading={aiLoading}
          />
        )}
        {aiError && (
          <div className="border-b bg-red-50 px-3 py-1.5 text-xs text-red-700">{aiError}</div>
        )}
        {showImageToolbar && editor && <ImageToolbar editor={editor} />}
        {showCodeBlockToolbar && editor && <CodeBlockToolbar editor={editor} />}
        {showTableToolbar && editor && <TableToolbar editor={editor} />}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div
            className="min-h-0 flex-1 overflow-y-auto p-4"
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
                <div className="rounded border bg-white shadow-lg">
                  <AiMenu onAction={applyAiAction} onOpenAssistant={openAssistant} loading={aiLoading} />
                </div>
              </BubbleMenu>
            )}
            <EditorContent
              editor={editor}
              className={`tiptap ${widthClass} ${mode === "wysiwyg" ? "" : "hidden"}`}
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
          {showHistory && <VersionHistoryPanel itemId={item.id} onClose={() => setShowHistory(false)} />}
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

      {pendingSpaceId && (
        <ConfirmDialog
          title={`Перенести заметку в спейс «${(spaces ?? []).find((s) => s.id === pendingSpaceId)?.name ?? ""}»? Папка сбросится, файлы внутри заметки останутся доступны.`}
          confirmLabel="Перенести"
          onConfirm={async () => {
            const spaceId = pendingSpaceId;
            setPendingSpaceId(null);
            await moveItemSpace.mutateAsync({ id: item.id, space_id: spaceId });
          }}
          onCancel={() => setPendingSpaceId(null)}
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
