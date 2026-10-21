import type { Editor } from "@tiptap/core";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlignCenter,
  Bold,
  ChevronLeft,
  ChevronRight,
  Code,
  FileUp,
  Heading1,
  Heading2,
  Heading3,
  Image as ImageIcon,
  Info,
  Italic,
  List,
  ListOrdered,
  ListTree,
  Maximize2,
  MessageSquare,
  Mic,
  Minus,
  Quote,
  Redo2,
  SquareCode,
  Strikethrough,
  StretchHorizontal,
  Table as TableIcon,
  TableProperties,
  Undo2,
} from "lucide-react";
import type { ContentWidth } from "../lib/storage";
import AiMenu, { type AiAction } from "./AiMenu";
import Spinner from "./Spinner";

function ToolbarButton({
  onClick,
  active,
  disabled,
  title,
  children,
}: {
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  title: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      disabled={disabled}
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl disabled:opacity-30 ${
        active ? "bg-accent text-on-accent" : "text-secondary hover:bg-muted-hover"
      }`}
    >
      {children}
    </button>
  );
}

export default function EditorToolbar({
  editor,
  onInsertImage,
  onInsertFile,
  onOpenRecorder,
  onInsertTable,
  uploadProgress,
  uploadBatch,
  contentWidth,
  onContentWidthChange,
  onAiAction,
  onOpenAssistant,
  aiLoading,
  readOnly,
  showToc,
  onToggleToc,
}: {
  editor: Editor | null;
  onInsertImage: () => void;
  onInsertFile: () => void;
  onOpenRecorder?: () => void;
  onInsertTable?: () => void;
  uploadProgress: number | null;
  uploadBatch: { current: number; total: number } | null;
  contentWidth: ContentWidth;
  onContentWidthChange: (width: ContentWidth) => void;
  onAiAction: (action: AiAction, instruction?: string) => void;
  onOpenAssistant?: () => void;
  aiLoading: boolean;
  // Режим "Просмотр" — панель не прячется целиком (в ней живут удобные
  // кнопки ширины и содержания), а блокируется: кнопки правки визуально
  // гаснут и не реагируют на клики, ширина/содержание остаются активными.
  readOnly: boolean;
  showToc: boolean;
  onToggleToc: () => void;
}) {
  // На телефоне панель шире экрана и прокручивается вбок, но полосы
  // прокрутки на тач-экранах не видно: кнопки просто обрываются у края, и
  // кажется, что остальных нет. Затухание и стрелка у края показывают, что
  // дальше есть ещё. На тач-экранах стрелка касаний не ловит: панель там
  // листают пальцем, и свайп, начатый у края, должен её прокрутить, а не
  // упереться в стрелку. Хуки — до раннего return ниже.
  const scrollRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const updateEdges = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const left = el.scrollLeft > 2;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 2;
    setEdges((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    updateEdges();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(updateEdges);
    observer.observe(el);
    return () => observer.disconnect();
  }, [updateEdges, editor]);
  const scrollBy = (dir: 1 | -1) => {
    const el = scrollRef.current;
    el?.scrollBy({ left: dir * el.clientWidth * 0.7, behavior: "smooth" });
  };

  if (!editor) return null;
  const uploading = uploadProgress !== null;

  return (
    <div className="relative border-b bg-muted">
    {edges.left && (
      <button
        type="button"
        title="Прокрутить панель влево"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => scrollBy(-1)}
        className="absolute inset-y-0 left-0 z-10 flex w-8 items-center justify-start [@media(pointer:coarse)]:pointer-events-none bg-gradient-to-r from-muted via-muted to-transparent pl-0.5 text-subtle"
      >
        <ChevronLeft size={16} />
      </button>
    )}
    {edges.right && (
      <button
        type="button"
        title="Прокрутить панель вправо"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => scrollBy(1)}
        className="absolute inset-y-0 right-0 z-10 flex w-8 items-center justify-end [@media(pointer:coarse)]:pointer-events-none bg-gradient-to-l from-muted via-muted to-transparent pr-0.5 text-subtle"
      >
        <ChevronRight size={16} />
      </button>
    )}
    <div
      ref={scrollRef}
      onScroll={updateEdges}
      className="flex flex-nowrap items-center gap-0.5 overflow-x-auto overscroll-x-contain px-2 py-1"
    >
      <div className={`flex flex-nowrap items-center gap-0.5 ${readOnly ? "pointer-events-none opacity-40" : ""}`}>
      <AiMenu onAction={onAiAction} onOpenAssistant={onOpenAssistant} loading={aiLoading} />
      <span className="mx-1 h-4 w-px shrink-0 bg-default" />
      <ToolbarButton
        title="Заголовок 1"
        active={editor.isActive("heading", { level: 1 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
      >
        <Heading1 size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Заголовок 2"
        active={editor.isActive("heading", { level: 2 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
      >
        <Heading2 size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Заголовок 3"
        active={editor.isActive("heading", { level: 3 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
      >
        <Heading3 size={16} />
      </ToolbarButton>
      <span className="mx-1 h-4 w-px shrink-0 bg-default" />
      <ToolbarButton
        title="Жирный"
        active={editor.isActive("bold")}
        onClick={() => editor.chain().focus().toggleBold().run()}
      >
        <Bold size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Курсив"
        active={editor.isActive("italic")}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      >
        <Italic size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Зачёркнутый"
        active={editor.isActive("strike")}
        onClick={() => editor.chain().focus().toggleStrike().run()}
      >
        <Strikethrough size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Код"
        active={editor.isActive("code")}
        onClick={() => editor.chain().focus().toggleCode().run()}
      >
        <Code size={16} />
      </ToolbarButton>
      <span className="mx-1 h-4 w-px shrink-0 bg-default" />
      <ToolbarButton
        title="Маркированный список"
        active={editor.isActive("bulletList")}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      >
        <List size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Нумерованный список"
        active={editor.isActive("orderedList")}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      >
        <ListOrdered size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Цитата"
        active={editor.isActive("blockquote")}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
      >
        <Quote size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Блок кода"
        active={editor.isActive("codeBlock")}
        onClick={() => editor.chain().focus().toggleCodeBlock().run()}
      >
        <SquareCode size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Спойлер"
        onClick={() =>
          editor
            .chain()
            .focus()
            .insertContent({ type: "callout", attrs: { variant: "spoiler", open: true }, content: [{ type: "paragraph" }] })
            .run()
        }
      >
        <MessageSquare size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Инфо-блок (совет/важно/опасно — переключается на самом блоке)"
        onClick={() =>
          editor
            .chain()
            .focus()
            .insertContent({ type: "callout", attrs: { variant: "info" }, content: [{ type: "paragraph" }] })
            .run()
        }
      >
        <Info size={16} />
      </ToolbarButton>
      <ToolbarButton title="Разделитель" onClick={() => editor.chain().focus().setHorizontalRule().run()}>
        <Minus size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Простая сетка"
        active={editor.isActive("table")}
        onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
      >
        <TableIcon size={16} />
      </ToolbarButton>
      {onInsertTable && (
        <ToolbarButton title="Таблица" onClick={onInsertTable}>
          <TableProperties size={16} />
        </ToolbarButton>
      )}
      <span className="mx-1 h-4 w-px shrink-0 bg-default" />
      <ToolbarButton title="Картинка" disabled={uploading} onClick={onInsertImage}>
        {uploading ? <Spinner size={16} /> : <ImageIcon size={16} />}
      </ToolbarButton>
      <ToolbarButton title="Файл" disabled={uploading} onClick={onInsertFile}>
        {uploading ? <Spinner size={16} /> : <FileUp size={16} />}
      </ToolbarButton>
      {onOpenRecorder && (
        <ToolbarButton title="Записать аудио" onClick={onOpenRecorder}>
          <Mic size={16} />
        </ToolbarButton>
      )}
      {uploading && (
        <span className="shrink-0 text-xs tabular-nums text-subtle">
          {uploadBatch && uploadBatch.total > 1 ? `${uploadBatch.current}/${uploadBatch.total} · ` : ""}
          {uploadProgress}%
        </span>
      )}
      <span className="mx-1 h-4 w-px shrink-0 bg-default" />
      <ToolbarButton title="Отменить" disabled={!editor.can().undo()} onClick={() => editor.chain().focus().undo().run()}>
        <Undo2 size={16} />
      </ToolbarButton>
      <ToolbarButton title="Повторить" disabled={!editor.can().redo()} onClick={() => editor.chain().focus().redo().run()}>
        <Redo2 size={16} />
      </ToolbarButton>
      </div>
      <span className="mx-1 h-4 w-px shrink-0 bg-default" />
      <ToolbarButton title="Узкий текст" active={contentWidth === "narrow"} onClick={() => onContentWidthChange("narrow")}>
        <AlignCenter size={16} />
      </ToolbarButton>
      <ToolbarButton title="Широкий текст" active={contentWidth === "wide"} onClick={() => onContentWidthChange("wide")}>
        <StretchHorizontal size={16} />
      </ToolbarButton>
      <ToolbarButton title="Во весь экран" active={contentWidth === "full"} onClick={() => onContentWidthChange("full")}>
        <Maximize2 size={16} />
      </ToolbarButton>
      <span className="mx-1 h-4 w-px shrink-0 bg-default" />
      <ToolbarButton title="Содержание заметки" active={showToc} onClick={onToggleToc}>
        <ListTree size={16} />
      </ToolbarButton>
    </div>
    </div>
  );
}
