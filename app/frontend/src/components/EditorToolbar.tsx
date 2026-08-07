import type { Editor } from "@tiptap/core";
import type { ReactNode } from "react";
import {
  AlignCenter,
  Bold,
  Code,
  FileUp,
  Heading1,
  Heading2,
  Heading3,
  Image as ImageIcon,
  Italic,
  List,
  ListOrdered,
  Maximize2,
  Minus,
  Quote,
  Redo2,
  SquareCode,
  Strikethrough,
  StretchHorizontal,
  Table as TableIcon,
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
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded disabled:opacity-30 ${
        active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
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
  uploading,
  contentWidth,
  onContentWidthChange,
  onAiAction,
  aiLoading,
}: {
  editor: Editor | null;
  onInsertImage: () => void;
  onInsertFile: () => void;
  uploading: boolean;
  contentWidth: ContentWidth;
  onContentWidthChange: (width: ContentWidth) => void;
  onAiAction: (action: AiAction, instruction?: string) => void;
  aiLoading: boolean;
}) {
  if (!editor) return null;

  return (
    <div className="flex flex-nowrap items-center gap-0.5 overflow-x-auto border-b bg-slate-50 px-2 py-1">
      <AiMenu onAction={onAiAction} loading={aiLoading} />
      <span className="mx-1 h-4 w-px shrink-0 bg-slate-300" />
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
      <span className="mx-1 h-4 w-px shrink-0 bg-slate-300" />
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
      <span className="mx-1 h-4 w-px shrink-0 bg-slate-300" />
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
      <ToolbarButton title="Разделитель" onClick={() => editor.chain().focus().setHorizontalRule().run()}>
        <Minus size={16} />
      </ToolbarButton>
      <ToolbarButton
        title="Таблица"
        active={editor.isActive("table")}
        onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
      >
        <TableIcon size={16} />
      </ToolbarButton>
      <span className="mx-1 h-4 w-px shrink-0 bg-slate-300" />
      <ToolbarButton title="Картинка" disabled={uploading} onClick={onInsertImage}>
        {uploading ? <Spinner size={16} /> : <ImageIcon size={16} />}
      </ToolbarButton>
      <ToolbarButton title="Файл" disabled={uploading} onClick={onInsertFile}>
        {uploading ? <Spinner size={16} /> : <FileUp size={16} />}
      </ToolbarButton>
      <span className="mx-1 h-4 w-px shrink-0 bg-slate-300" />
      <ToolbarButton title="Отменить" disabled={!editor.can().undo()} onClick={() => editor.chain().focus().undo().run()}>
        <Undo2 size={16} />
      </ToolbarButton>
      <ToolbarButton title="Повторить" disabled={!editor.can().redo()} onClick={() => editor.chain().focus().redo().run()}>
        <Redo2 size={16} />
      </ToolbarButton>
      <span className="mx-1 h-4 w-px shrink-0 bg-slate-300" />
      <ToolbarButton title="Узкий текст" active={contentWidth === "narrow"} onClick={() => onContentWidthChange("narrow")}>
        <AlignCenter size={16} />
      </ToolbarButton>
      <ToolbarButton title="Широкий текст" active={contentWidth === "wide"} onClick={() => onContentWidthChange("wide")}>
        <StretchHorizontal size={16} />
      </ToolbarButton>
      <ToolbarButton title="Во весь экран" active={contentWidth === "full"} onClick={() => onContentWidthChange("full")}>
        <Maximize2 size={16} />
      </ToolbarButton>
    </div>
  );
}
