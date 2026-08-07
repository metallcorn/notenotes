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
import { ChevronLeft, Code2, Eye, History, Palette, Pin, PinOff, Trash2 } from "lucide-react";
import { uiStorage, type ContentWidth } from "../lib/storage";
import { downloadFile, inlineImages, sanitizeFilename, wrapHtmlDocument } from "../lib/export";
import {
  useAddItemTag,
  useAiTransform,
  useCreateTag,
  useDeleteItem,
  useFolders,
  useItem,
  useRemoveItemTag,
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
import ExportMenu from "./ExportMenu";
import { ResizableImage } from "../extensions/ResizableImage";
import { Video } from "../extensions/Video";
import { SlashCommand } from "../extensions/SlashCommand";

const EmojiPickerPopover = lazy(() => import("./EmojiPickerPopover"));
const lowlight = createLowlight(common);

type Mode = "wysiwyg" | "raw";

const COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#a855f7", "#ec4899"];

export default function NoteEditor({
  itemId,
  onDeleted,
  onBack,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
}) {
  const { data: item, isError } = useItem(itemId);
  const updateItem = useUpdateItem();
  const deleteItem = useDeleteItem(item?.space_id);
  const uploadFile = useUploadFile(item?.space_id);
  const { data: allTags } = useTags();
  const addTag = useAddItemTag(itemId);
  const removeTag = useRemoveItemTag(itemId);
  const createTag = useCreateTag();
  const { data: folders } = useFolders(item?.space_id);
  const aiTransform = useAiTransform();

  const [mode, setMode] = useState<Mode>("wysiwyg");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [showHistory, setShowHistory] = useState(false);
  const [showTagPicker, setShowTagPicker] = useState(false);
  const [tagQuery, setTagQuery] = useState("");
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [showColorPicker, setShowColorPicker] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [contentWidth, setContentWidth] = useState<ContentWidth>(() => uiStorage.getContentWidth());
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const savedRef = useRef({ title: "", content: "" });
  const pendingRef = useRef<{ id: string; title: string; content: string } | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ codeBlock: false }),
      CodeBlockLowlight.configure({ lowlight }),
      ResizableImage,
      Video,
      LinkExtension.configure({ HTMLAttributes: { target: "_blank", rel: "noopener noreferrer" } }),
      Table.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      Markdown.configure({ html: true, transformPastedText: true }),
      SlashCommand.configure({
        onInsertImage: () => imageInputRef.current?.click(),
      }),
    ],
    content: "",
    onUpdate: ({ editor }) => setContent(editor.storage.markdown.getMarkdown()),
  });

  // Заметки больше нет (удалили в другой вкладке, или это протухшая ссылка
  // «последняя открытая заметка» из localStorage) — не зависаем на вечной
  // загрузке, а просто сбрасываем выбор.
  useEffect(() => {
    if (isError) onDeleted();
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id]);

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

  async function onPickImage(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !item) return;
    const uploaded = await uploadFile.mutateAsync(file);
    if (mode === "wysiwyg" && editor) {
      editor.chain().focus().setImage({ src: uploaded.url }).run();
    } else {
      setContent((c) => `${c}\n\n![](${uploaded.url})\n`);
    }
  }

  async function onPickFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !item) return;
    const uploaded = await uploadFile.mutateAsync(file);
    const isVideo = uploaded.content_type.startsWith("video/");
    if (mode === "wysiwyg" && editor) {
      if (isVideo) {
        editor
          .chain()
          .focus()
          .insertContent({ type: "video", attrs: { src: uploaded.url, filename: uploaded.filename } })
          .run();
      } else {
        editor
          .chain()
          .focus()
          .insertContent({ type: "text", text: uploaded.filename, marks: [{ type: "link", attrs: { href: uploaded.url } }] })
          .run();
      }
    } else if (isVideo) {
      setContent(
        (c) => `${c}\n\n<video src="${uploaded.url}" controls preload="metadata" style="max-width: 100%;"></video>\n`,
      );
    } else {
      setContent((c) => `${c}\n\n[${uploaded.filename}](${uploaded.url})\n`);
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
      <div className="flex flex-wrap items-center gap-2 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 md:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="relative">
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
          className="min-w-[160px] flex-1 text-lg font-semibold outline-none"
        />
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
        {item.tags.map((tag) => (
          <span
            key={tag.id}
            className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
          >
            #{tag.name}
            <button onClick={() => removeTag.mutate(tag.id)} className="text-slate-400 hover:text-red-600">
              ×
            </button>
          </span>
        ))}
        <div className="relative">
          <button
            onClick={() => {
              setShowTagPicker((v) => !v);
              setTagQuery("");
            }}
            className="rounded-full border border-dashed px-2 py-0.5 text-xs text-slate-400 hover:text-slate-700"
          >
            + тег
          </button>
          {showTagPicker && (
            <div className="absolute z-10 mt-1 w-52 rounded border bg-white p-1 shadow-lg">
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

        <div className="ml-auto flex shrink-0 items-center gap-1">
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

      <input ref={imageInputRef} type="file" accept="image/*" hidden onChange={onPickImage} />
      <input ref={fileInputRef} type="file" hidden onChange={onPickFile} />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {mode === "wysiwyg" && (
          <EditorToolbar
            editor={editor}
            onInsertImage={() => imageInputRef.current?.click()}
            onInsertFile={() => fileInputRef.current?.click()}
            uploading={uploadFile.isPending}
            contentWidth={contentWidth}
            onContentWidthChange={changeContentWidth}
            onAiAction={applyAiAction}
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
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {mode === "wysiwyg" ? (
              <>
                {editor && (
                  <BubbleMenu editor={editor} shouldShow={({ state }) => !state.selection.empty}>
                    <div className="rounded border bg-white shadow-lg">
                      <AiMenu onAction={applyAiAction} loading={aiLoading} />
                    </div>
                  </BubbleMenu>
                )}
                <EditorContent editor={editor} className={`tiptap ${widthClass}`} />
              </>
            ) : (
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
    </div>
  );
}
