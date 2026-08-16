import { useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronUp } from "lucide-react";
import { RecognizedTextCopyButtons, recognizedTextMarkdownComponents } from "./RecognizedTextView";

// Тот же спойлер-паттерн, что DocumentAttachmentCard.tsx использует для
// распознанного текста PDF — свёрнуто по умолчанию, картинка (обычный
// <img> перед этим узлом) уже видна сама по себе, текст нужен не всегда.
// Рендер и кнопки копирования — общий модуль RecognizedTextView.tsx, не
// копия: тот же текстовый формат (заголовки/таблицы/списки из промпта
// распознавания), та же пара "форматированная копия"/"копия как MD".
export default function ImageOcrResultCard({ node }: NodeViewProps) {
  const { text } = node.attrs as { text: string };
  const [expanded, setExpanded] = useState(false);

  if (!text) return null;

  return (
    <NodeViewWrapper as="div" className="my-1 inline-block max-w-full" data-drag-handle draggable>
      <div className="max-w-full rounded border bg-slate-50">
        <div className="flex items-center">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex min-w-0 flex-1 items-center gap-1 px-3 py-1.5 text-left text-xs text-slate-500 hover:bg-slate-100"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Скрыть распознанный текст" : "Показать распознанный текст"}
          </button>
          <RecognizedTextCopyButtons text={text} />
        </div>
        {expanded && (
          // contentEditable=true открывает свою "зону редактирования" —
          // без этого клик-протяг внутри contenteditable=false NodeView
          // выделяет весь узел целиком, а не часть текста (тот же приём и
          // та же причина, что в DocumentAttachmentCard.tsx). Печатать
          // сюда по-прежнему нельзя — onKeyDown/onPaste/onBeforeInput
          // блокируют реальный ввод. stopPropagation на mousedown — иначе
          // data-drag-handle/draggable у обёртки перехватывает жест мышью
          // раньше, чем браузер поймёт, что это выделение текста, а не
          // перетаскивание узла (тот же найденный баг, что и у PDF-карточки).
          <div
            contentEditable
            suppressContentEditableWarning
            draggable={false}
            onKeyDown={(e) => e.preventDefault()}
            onPaste={(e) => e.preventDefault()}
            onBeforeInput={(e) => e.preventDefault()}
            onDragStart={(e) => e.preventDefault()}
            onMouseDown={(e) => e.stopPropagation()}
            className="max-h-96 cursor-text select-text overflow-y-auto border-t px-3 py-2 text-xs text-slate-700 outline-none"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={recognizedTextMarkdownComponents}>
              {text}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </NodeViewWrapper>
  );
}
