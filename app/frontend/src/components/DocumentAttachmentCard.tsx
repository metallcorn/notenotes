import { useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp, File, FileText } from "lucide-react";
import { useReprocessUpload } from "../api/hooks";
import Spinner from "./Spinner";

const UPLOAD_ID_RE = /\/api\/uploads\/([0-9a-f-]{36})/i;

export default function DocumentAttachmentCard({ node, editor, getPos }: NodeViewProps) {
  const { url, filename, text } = node.attrs as { url: string; filename: string; text: string };
  const [expanded, setExpanded] = useState(false);
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
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-3 py-2 text-sm text-slate-800 no-underline hover:bg-slate-100"
        >
          {isPdf ? (
            <FileText size={16} className="shrink-0 text-red-500" />
          ) : (
            <File size={16} className="shrink-0 text-slate-400" />
          )}
          <span className="max-w-xs truncate font-medium">{filename || url}</span>
        </a>

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
          <div className="max-h-96 overflow-y-auto whitespace-pre-wrap border-t px-3 py-2 text-xs text-slate-700">
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
    </NodeViewWrapper>
  );
}
