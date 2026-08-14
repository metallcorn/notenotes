import { useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp } from "lucide-react";

// Тот же спойлер-паттерн, что DocumentAttachmentCard.tsx использует для
// распознанного текста PDF — свёрнуто по умолчанию, картинка (обычный
// <img> перед этим узлом) уже видна сама по себе, текст нужен не всегда.
export default function ImageOcrResultCard({ node }: NodeViewProps) {
  const { text } = node.attrs as { text: string };
  const [expanded, setExpanded] = useState(false);

  if (!text) return null;

  return (
    <NodeViewWrapper as="div" className="my-1 inline-block max-w-full" data-drag-handle draggable>
      <div className="max-w-full rounded border bg-slate-50">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center gap-1 px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100"
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {expanded ? "Скрыть распознанный текст" : "Показать распознанный текст"}
        </button>
        {expanded && (
          // contentEditable=true открывает свою "зону редактирования" —
          // без этого клик-протяг внутри contenteditable=false NodeView
          // выделяет весь узел целиком, а не часть текста (тот же приём и
          // та же причина, что в DocumentAttachmentCard.tsx). Печатать
          // сюда по-прежнему нельзя — onKeyDown/onPaste/onBeforeInput
          // блокируют реальный ввод.
          <div
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
      </div>
    </NodeViewWrapper>
  );
}
