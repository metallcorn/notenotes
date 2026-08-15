import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, ChevronDown, ChevronUp, Copy, Download, File, FileText, X } from "lucide-react";
import { useReprocessUpload } from "../api/hooks";
import { useIsPartOfAttachmentStack, useTapReveal } from "../lib/useNodeViewPreview";
import Spinner from "./Spinner";

const UPLOAD_ID_RE = /\/api\/uploads\/([0-9a-f-]{36})/i;

// Реальная жалоба: распознанный текст (OCR/PDF) показывался как ПЛОСКИЙ
// текст — заголовки/таблицы/списки из промпта распознавания (см. vision.py,
// pdf_processing.py) просто лежали как есть, не отформатированные. Своя,
// компактная версия стилей — не modules-scope у AssistantChat.tsx: там для
// чата с картинками-превью, здесь мельче (text-xs) и без картинок.
const docMarkdownComponents: Components = {
  h1: (props) => <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0" {...props} />,
  h2: (props) => <h4 className="mb-1 mt-2 text-sm font-semibold first:mt-0" {...props} />,
  h3: (props) => <h5 className="mb-1 mt-2 text-xs font-semibold first:mt-0" {...props} />,
  p: (props) => <p className="mb-1.5 last:mb-0" {...props} />,
  ul: (props) => <ul className="mb-1.5 list-disc pl-4 last:mb-0" {...props} />,
  ol: (props) => <ol className="mb-1.5 list-decimal pl-4 last:mb-0" {...props} />,
  table: (props) => (
    <div className="mb-1.5 overflow-x-auto">
      <table className="border-collapse text-xs" {...props} />
    </div>
  ),
  th: (props) => <th className="border border-slate-300 bg-slate-100 px-1.5 py-1 text-left font-medium" {...props} />,
  td: (props) => <td className="border border-slate-300 px-1.5 py-1" {...props} />,
  code: (props) => <code className="rounded bg-slate-100 px-1 py-0.5 text-[11px]" {...props} />,
  pre: (props) => <pre className="mb-1.5 overflow-x-auto rounded bg-slate-100 p-2 text-[11px] last:mb-0" {...props} />,
  a: ({ node: _node, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline" />
  ),
};

// Нативный <iframe> — все актуальные браузеры (включая мобильные) рендерят
// PDF во встроенном просмотрщике сами, со своими зумом/листанием/печатью/
// скачиванием — не нужна ни одна новая зависимость (в отличие от PyMuPDF на
// бэкенде, тут наоборот: браузер и так всё умеет).
function PdfPreviewOverlay({ url, onClose }: { url: string; onClose: () => void }) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/80 p-2 sm:p-6">
      <button
        onClick={onClose}
        title="Закрыть (Esc)"
        className="mb-2 flex h-9 w-9 shrink-0 items-center justify-center self-end rounded-full bg-black/50 text-white hover:bg-black/70"
      >
        <X size={18} />
      </button>
      {/* Клик внутри — взаимодействие с самим PDF-просмотрщиком браузера
          (скролл/зум/его кнопки), поэтому закрытие только по ✕/Escape, не
          по клику на содержимое или фон — иначе случайный клик по PDF
          закрывал бы весь оверлей. */}
      <iframe src={url} title={url} className="min-h-0 w-full flex-1 rounded bg-white" />
    </div>
  );
}

// Всплывающая мини-превьюшка страницы PDF по ховеру/тапу — тот же приём
// (портал в body, без position: absolute внутри редактора), что
// HoverPopover в LinkPreviewCard.tsx: редактор сам overflow-контейнер,
// абсолютное позиционирование внутри него обрезалось бы.
function ThumbnailPopover({ anchor, thumbnailUrl }: { anchor: HTMLElement; thumbnailUrl: string }) {
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    const rect = anchor.getBoundingClientRect();
    setPosition({ top: rect.bottom + 4, left: rect.left });
  }, [anchor]);

  if (!position) return null;

  return createPortal(
    <div style={{ top: position.top, left: position.left }} className="fixed z-50 overflow-hidden rounded border bg-white shadow-lg">
      <img src={thumbnailUrl} alt="" className="max-h-64 w-48 object-cover object-top" />
    </div>,
    document.body,
  );
}

export default function DocumentAttachmentCard({ node, editor, getPos }: NodeViewProps) {
  const { url, filename, text } = node.attrs as { url: string; filename: string; text: string };
  const [expanded, setExpanded] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [thumbFailed, setThumbFailed] = useState(false);
  const [hovered, setHovered] = useState(false);
  const reprocess = useReprocessUpload();
  const stacked = useIsPartOfAttachmentStack(editor, getPos);
  const { revealed, handleTap } = useTapReveal();

  const isPdf = filename.toLowerCase().endsWith(".pdf");
  const uploadId = url.match(UPLOAD_ID_RE)?.[1] ?? null;
  const thumbnailUrl = isPdf && uploadId && !thumbFailed ? `${url}/thumbnail` : null;
  const rowRef = useRef<HTMLDivElement>(null);
  const [copiedKind, setCopiedKind] = useState<"formatted" | "md" | null>(null);
  // Скрытый, но реально отрендеренный markdown — источник HTML для
  // "Скопировать" (форматированный вариант). Не завязан на expanded: кнопка
  // должна работать, даже если спойлер сейчас свёрнут.
  const hiddenMdRef = useRef<HTMLDivElement>(null);

  async function copyFormatted() {
    try {
      const html = hiddenMdRef.current?.innerHTML ?? "";
      // ClipboardItem с двумя MIME сразу — вставка в Google Docs/Word/Notion
      // возьмёт text/html и сохранит форматирование; вставка в обычное
      // текстовое поле — возьмёт text/plain как обычно.
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        }),
      ]);
    } catch {
      // Старые браузеры без ClipboardItem/text-html — хотя бы сырой текст.
      await navigator.clipboard.writeText(text);
    }
    setCopiedKind("formatted");
    setTimeout(() => setCopiedKind(null), 1500);
  }

  async function copyMarkdown() {
    await navigator.clipboard.writeText(text);
    setCopiedKind("md");
    setTimeout(() => setCopiedKind(null), 1500);
  }

  async function handleReprocess() {
    if (!uploadId || typeof getPos !== "function") return;
    // Плейсхолдер — та же строка, что backend ищет и заменяет
    // (pdf_processing.placeholder_text) на готовую карточку с текстом.
    const placeholder = `⏳ Распознавание PDF ${uploadId} обрабатывается…`;
    const pos = getPos();
    editor
      .chain()
      .focus()
      .deleteRange({ from: pos, to: pos + node.nodeSize })
      .insertContentAt(pos, { type: "paragraph", content: [{ type: "text", text: placeholder }] })
      .run();
    await reprocess.mutateAsync(uploadId);
  }

  // Подборка (пачка файлов/ссылок подряд) — превью сразу, без действия;
  // одиночный файл среди текста — компактно, превью по ховеру (мышь) или
  // первому тапу (тач-экран, второй тап открывает — см. useTapReveal).
  const showBanner = stacked && thumbnailUrl;
  const showHoverPreview = !stacked && (hovered || revealed) && thumbnailUrl && rowRef.current;

  return (
    <NodeViewWrapper as="div" className="my-1" data-drag-handle draggable>
      <div className={`overflow-hidden rounded border bg-slate-50 ${stacked ? "max-w-md" : "inline-block max-w-full"}`}>
        {showBanner && (
          <img
            src={thumbnailUrl!}
            alt=""
            className="h-40 w-full cursor-pointer object-cover object-top"
            onClick={() => setPreviewOpen(true)}
            onError={() => setThumbFailed(true)}
          />
        )}
        <div
          ref={rowRef}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          className="flex items-center"
        >
          {isPdf ? (
            <button
              onClick={(e) => (stacked ? setPreviewOpen(true) : handleTap(e, () => setPreviewOpen(true)))}
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm text-slate-800 hover:bg-slate-100"
            >
              <FileText size={16} className="shrink-0 text-red-500" />
              <span className="max-w-xs truncate font-medium">{filename || url}</span>
            </button>
          ) : (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-sm text-slate-800 no-underline hover:bg-slate-100"
            >
              <File size={16} className="shrink-0 text-slate-400" />
              <span className="max-w-xs truncate font-medium">{filename || url}</span>
            </a>
          )}
          {isPdf && (
            <a
              href={url}
              download={filename || undefined}
              title="Скачать"
              className="flex h-9 w-9 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
            >
              <Download size={14} />
            </a>
          )}
          {text && (
            <>
              <button
                type="button"
                onClick={copyFormatted}
                title="Скопировать форматированным (для Docs/Word/Notion)"
                className="flex h-9 w-9 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
              >
                {copiedKind === "formatted" ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
              </button>
              <button
                type="button"
                onClick={copyMarkdown}
                title="Скопировать как Markdown"
                className="flex h-9 shrink-0 items-center justify-center px-2 text-[10px] font-medium text-slate-400 hover:text-slate-700"
              >
                {copiedKind === "md" ? <Check size={14} className="text-emerald-600" /> : "MD"}
              </button>
            </>
          )}
        </div>
        {showHoverPreview && <ThumbnailPopover anchor={rowRef.current!} thumbnailUrl={thumbnailUrl!} />}

        {text && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex w-full items-center gap-1 border-t px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded
              ? isPdf ? "Скрыть распознанный текст" : "Скрыть содержимое файла"
              : isPdf ? "Показать распознанный текст" : "Показать содержимое файла"}
          </button>
        )}
        {text && expanded && (
          // atom-узел целиком лежит в contentEditable={false} (NodeView
          // без contentDOM — см. addNodeView) — а браузеры по спецификации
          // редактирования обращаются с contenteditable=false "островом"
          // внутри contenteditable=true родителя как с ОДНИМ неделимым
          // блоком выделения: клик-протяг куда угодно внутри всегда
          // выделяет остров целиком (реальная жалоба — не баг конкретно
          // ProseMirror, поведение самого браузера). contentEditable=true
          // здесь заново открывает вложенную "зону редактирования" именно
          // для этого блока — она уже ведёт себя как обычный текст с
          // нормальным частичным выделением. Печатать в него по-прежнему
          // нельзя: onKeyDown/onPaste/onBeforeInput блокируют реальный ввод,
          // а data-doc-text — маркер для stopEvent в DocumentAttachment.ts,
          // чтобы ProseMirror не пытался сам обработать эти события.
          <div
            data-doc-text
            contentEditable
            suppressContentEditableWarning
            draggable={false}
            onKeyDown={(e) => e.preventDefault()}
            onPaste={(e) => e.preventDefault()}
            onBeforeInput={(e) => e.preventDefault()}
            onDragStart={(e) => e.preventDefault()}
            // Реальная жалоба: даже с contentEditable-трюком выше клик-протяг
            // мышью внутри не выделял текст — вся карточка целиком имеет
            // data-drag-handle/draggable (drag-to-reorder узла в редакторе),
            // и это, судя по всему, перехватывало сам жест мышью раньше, чем
            // браузер успевал понять, что это выделение текста, а не
            // перетаскивание. stopPropagation на mousedown не даёт этому
            // событию вообще всплыть до узла с data-drag-handle — жест
            // остаётся только "выделение", drag не запускается.
            onMouseDown={(e) => e.stopPropagation()}
            className="max-h-96 cursor-text select-text overflow-y-auto border-t px-3 py-2 text-xs text-slate-700 outline-none"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={docMarkdownComponents}>
              {text}
            </ReactMarkdown>
          </div>
        )}
        {/* Скрытый, но реально отрендеренный markdown — источник HTML для
            copyFormatted (кнопка "Скопировать" выше). display:none тут не
            нужен для доступа к innerHTML, но незачем занимать место в
            раскладке при свёрнутом спойлере. */}
        {text && (
          <div ref={hiddenMdRef} className="hidden">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={docMarkdownComponents}>
              {text}
            </ReactMarkdown>
          </div>
        )}

        {!text && isPdf && uploadId && (
          <button
            onClick={handleReprocess}
            disabled={reprocess.isPending}
            className="flex w-full items-center gap-1.5 border-t px-3 py-1.5 text-xs text-violet-600 hover:bg-violet-50 disabled:opacity-50"
          >
            {reprocess.isPending ? <Spinner size={12} /> : null}
            Распознать текст
          </button>
        )}
      </div>
      {previewOpen && <PdfPreviewOverlay url={url} onClose={() => setPreviewOpen(false)} />}
    </NodeViewWrapper>
  );
}
