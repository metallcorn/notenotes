import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { FileText } from "lucide-react";
import type { NoteLinkOptions } from "../extensions/NoteLink";

// Клик — переход ВНУТРИ приложения (onOpen из опций расширения, см.
// NoteEditor.tsx::onOpenItem), не обычная навигация по href: заметка живёт
// по /?item=<id>, открытие по-настоящему новой страницей потеряло бы
// остальное состояние приложения (список заметок, открытый спейс и т.п.).
export default function NoteLinkCard({ node, extension }: NodeViewProps) {
  const { itemId, title } = node.attrs as { itemId: string | null; title: string };
  const { onOpen } = extension.options as NoteLinkOptions;

  return (
    <NodeViewWrapper as="span" className="inline-block">
      <button
        onClick={() => itemId && onOpen(itemId)}
        contentEditable={false}
        className="inline-flex items-center gap-1 rounded bg-violet-50 px-1.5 py-0.5 align-baseline text-sm font-medium text-violet-700 hover:bg-violet-100"
      >
        <FileText size={12} className="shrink-0" />
        {title || "Заметка"}
      </button>
    </NodeViewWrapper>
  );
}
