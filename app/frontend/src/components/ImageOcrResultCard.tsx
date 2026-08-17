import { useRef, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { ExpandedTextPanel, RecognizedTextCopyButtons } from "./RecognizedTextView";

// Тот же спойлер-паттерн, что DocumentAttachmentCard.tsx использует для
// распознанного текста PDF — свёрнуто по умолчанию, картинка (обычный
// <img> перед этим узлом) уже видна сама по себе, текст нужен не всегда.
// Рендер и кнопки копирования — общий модуль RecognizedTextView.tsx, не
// копия: тот же текстовый формат (заголовки/таблицы/списки из промпта
// распознавания), та же пара "форматированная копия"/"копия как MD".
export default function ImageOcrResultCard({ node }: NodeViewProps) {
  const { text } = node.attrs as { text: string };
  const [expanded, setExpanded] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  if (!text) return null;

  return (
    // Реальный корень бага (найден чтением исходников @tiptap/core): дело
    // не только в data-drag-handle — ГЛАВНОЕ, что сам HTML-атрибут
    // draggable=true на NodeViewWrapper браузер распознаёт независимо от
    // data-drag-handle. draggable теперь ТОЛЬКО на строке с кнопкой ниже.
    <NodeViewWrapper as="div" className="my-1 inline-block max-w-full">
      <div ref={cardRef} className="max-w-full rounded border bg-slate-50">
        <div data-drag-handle draggable className="flex items-center">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex min-w-0 flex-1 items-center gap-1 px-3 py-1.5 text-left text-xs text-slate-500 hover:bg-slate-100"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Скрыть распознанный текст" : "Показать распознанный текст"}
          </button>
          <RecognizedTextCopyButtons text={text} />
        </div>
        {expanded && <ExpandedTextPanel anchorRef={cardRef} text={text} />}
      </div>
    </NodeViewWrapper>
  );
}
