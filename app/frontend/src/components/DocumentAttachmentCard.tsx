import { useEffect, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp, Download, File, FileText, X } from "lucide-react";
import { useReprocessUpload } from "../api/hooks";
import Spinner from "./Spinner";

const UPLOAD_ID_RE = /\/api\/uploads\/([0-9a-f-]{36})/i;

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

export default function DocumentAttachmentCard({ node, editor, getPos }: NodeViewProps) {
  const { url, filename, text } = node.attrs as { url: string; filename: string; text: string };
  const [expanded, setExpanded] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const reprocess = useReprocessUpload();

  const isPdf = filename.toLowerCase().endsWith(".pdf");
  const uploadId = url.match(UPLOAD_ID_RE)?.[1] ?? null;

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

  return (
    <NodeViewWrapper as="div" className="my-1" data-drag-handle draggable>
      <div className="inline-block max-w-full rounded border bg-slate-50">
        <div className="flex items-center">
          {isPdf ? (
            <button
              onClick={() => setPreviewOpen(true)}
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
        </div>

        {text && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex w-full items-center gap-1 border-t px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Скрыть распознанный текст" : "Показать распознанный текст"}
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
            className="max-h-96 cursor-text select-text overflow-y-auto whitespace-pre-wrap border-t px-3 py-2 text-xs text-slate-700 outline-none"
          >
            {text}
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
