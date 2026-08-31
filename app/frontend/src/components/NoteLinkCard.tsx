import { useEffect } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { FileText } from "lucide-react";
import { useItemBrief } from "../api/hooks";
import type { NoteLinkOptions } from "../extensions/NoteLink";

// Клик — переход ВНУТРИ приложения (onOpen из опций расширения, см.
// NoteEditor.tsx::onOpenItem), не обычная навигация по href: заметка живёт
// по /?item=<id>, открытие по-настоящему новой страницей потеряло бы
// остальное состояние приложения (список заметок, открытый спейс и т.п.).
//
// title пустой — узел вставлен НЕ через автокомплит [[ (где название уже
// известно), а как распознанная ссылка на свою заметку, вставленная голым
// URL из адресной строки браузера (NoteEditor.tsx::parseInternalNoteLink).
// В момент вставки известен только id — название подтягиваем сами и
// дописываем в атрибут узла, чтобы дальше показывалось сразу, без запроса.
export default function NoteLinkCard({ node, extension, updateAttributes }: NodeViewProps) {
  const { itemId, title } = node.attrs as { itemId: string | null; title: string };
  const { onOpen } = extension.options as NoteLinkOptions;
  const needsTitle = !title && !!itemId;
  const { data: fetched, isError } = useItemBrief(needsTitle ? itemId! : undefined);

  useEffect(() => {
    if (fetched && !title) updateAttributes({ title: fetched.title || "Без названия" });
  }, [fetched]); // eslint-disable-line react-hooks/exhaustive-deps

  const displayTitle = title || (isError ? "Заметка недоступна" : fetched?.title) || "Заметка";

  return (
    <NodeViewWrapper as="span" className="inline-block">
      <button
        onClick={() => itemId && !isError && onOpen(itemId)}
        disabled={isError}
        contentEditable={false}
        className="inline-flex items-center gap-1 rounded bg-brand/10 px-1.5 py-0.5 align-baseline text-sm font-medium text-brand hover:bg-brand/15 disabled:cursor-default disabled:bg-muted-hover disabled:text-subtle disabled:hover:bg-muted-hover"
      >
        <FileText size={12} className="shrink-0" />
        {displayTitle}
      </button>
    </NodeViewWrapper>
  );
}
