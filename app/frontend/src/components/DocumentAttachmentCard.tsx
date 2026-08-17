import { useEffect, useRef, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp, Download, File, FileText, RotateCw, X } from "lucide-react";
import { useReprocessUpload } from "../api/hooks";
import { ExpandedTextPanel, RecognizedTextCopyButtons } from "./RecognizedTextView";
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

export default function DocumentAttachmentCard({ node, editor }: NodeViewProps) {
  const { url, filename, text, processing } = node.attrs as {
    url: string;
    filename: string;
    text: string;
    processing?: boolean;
  };
  const [expanded, setExpanded] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [thumbFailed, setThumbFailed] = useState(false);
  const reprocess = useReprocessUpload();
  const cardRef = useRef<HTMLDivElement>(null);

  const isPdf = filename.toLowerCase().endsWith(".pdf");
  const uploadId = url.match(UPLOAD_ID_RE)?.[1] ?? null;
  // documentAttachment — блочный atom-узел (extensions/DocumentAttachment.ts,
  // group: "block"), у него физически не бывает текста слева/справа на той
  // же строке — только соседние абзацы сверху/снизу, которые сюда не
  // относятся (то же самое уже сделано для ссылок, LinkPreviewCard.tsx).
  // Превью поэтому показывается сразу всегда, без наведения/тапа.
  const thumbnailUrl = isPdf && uploadId && !thumbFailed ? `${url}/thumbnail` : null;

  // Реальная жалоба: раньше карточка файла на время распознавания
  // целиком заменялась текстовым плейсхолдером — файл нельзя было
  // открыть/скачать до конца обработки. Теперь узел тот же самый (url
  // никуда не девается), меняем только атрибут — backend сам сбросит его
  // обратно на готовый текст (или, при ошибке, на processing=false, чтобы
  // кнопка снова появилась — pdf_processing.py::_process/_fail).
  async function handleReprocess() {
    if (!uploadId) return;
    editor.chain().focus().updateAttributes("documentAttachment", { processing: true }).run();
    await reprocess.mutateAsync(uploadId);
  }

  // Распознавание заметно улучшилось (постранично причёсанная вёрстка,
  // document_reflow.py) — кнопка "распознать заново" рядом с остальными
  // имеет смысл и для УЖЕ распознанных старых файлов, не только для
  // пустых. Но здесь есть что терять — текущий результат заменится новым
  // (не факт, что лучшим), поэтому только для этого случая подтверждение.
  function handleReprocessWithConfirm() {
    if (!uploadId) return;
    if (window.confirm("Распознать заново? Текущий распознанный текст будет заменён новым результатом.")) {
      void handleReprocess();
    }
  }

  return (
    // Реальный найденный баг: HTML-атрибут draggable="true" на всей
    // обёртке — браузер распознаёт "тащить мышью" по БЛИЖАЙШЕМУ ПРЕДКУ с
    // draggable=true, независимо от data-drag-handle (это отдельная,
    // чисто внутренняя проверка TipTap, срабатывающая уже ПОСЛЕ того, как
    // браузер решил, что это перетаскивание, а не выделение текста).
    // draggable теперь ТОЛЬКО на строке с именем файла (dragstart
    // всплывает, обработчик NodeViewWrapper всё равно сработает).
    <NodeViewWrapper as="div" className="my-1">
      <div ref={cardRef} className="max-w-md overflow-hidden rounded border bg-slate-50">
        {thumbnailUrl && (
          <img
            src={thumbnailUrl}
            alt=""
            className="h-40 w-full cursor-pointer object-cover object-top"
            onClick={() => setPreviewOpen(true)}
            onError={() => setThumbFailed(true)}
          />
        )}
        <div data-drag-handle draggable className="flex items-center">
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
          {!processing && text && isPdf && uploadId && (
            <button
              onClick={handleReprocessWithConfirm}
              disabled={reprocess.isPending}
              title="Распознать заново"
              className="flex h-9 w-9 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700 disabled:opacity-50"
            >
              {reprocess.isPending ? <Spinner size={14} /> : <RotateCw size={14} />}
            </button>
          )}
          {text && <RecognizedTextCopyButtons text={text} />}
        </div>

        {processing ? (
          <div className="flex items-center gap-1.5 border-t px-3 py-1.5 text-xs text-violet-600">
            <Spinner size={12} />
            Распознаём…
          </div>
        ) : (
          text && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex w-full items-center gap-1 border-t px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100"
            >
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {expanded
                ? isPdf ? "Скрыть распознанный текст" : "Скрыть содержимое файла"
                : isPdf ? "Показать распознанный текст" : "Показать содержимое файла"}
            </button>
          )
        )}
        {text && expanded && <ExpandedTextPanel anchorRef={cardRef} text={text} />}

        {!processing && !text && isPdf && uploadId && (
          <div className="border-t px-3 py-1.5">
            <button
              onClick={handleReprocess}
              disabled={reprocess.isPending}
              className="flex items-center gap-1.5 text-xs text-violet-600 hover:opacity-80 disabled:opacity-50"
            >
              {reprocess.isPending ? <Spinner size={12} /> : null}
              Распознать текст
            </button>
            {/* Реальная жалоба: непонятно, почему для этого файла нет
                результата — молча ждать клика неочевидно. Точную причину
                (>5 МБ vs выключенная автообработка) фронт не знает
                достоверно, поэтому формулировка общая, не точечная. */}
            <div className="mt-0.5 text-[11px] text-slate-400">
              Не распознано автоматически — файл больше 5 МБ или автообработка выключена в настройках
            </div>
          </div>
        )}
      </div>
      {previewOpen && <PdfPreviewOverlay url={url} onClose={() => setPreviewOpen(false)} />}
    </NodeViewWrapper>
  );
}
