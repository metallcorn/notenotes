import type { Editor } from "@tiptap/core";
import { useState, type ComponentProps } from "react";
import { Bold, Image as ImageIcon, List, ListChecks, Mic, Plus, Sparkles, X } from "lucide-react";
import { useKeyboardInset } from "../lib/useKeyboardInset";
import EditorToolbar from "./EditorToolbar";
import Spinner from "./Spinner";

// Панель форматирования на телефоне (макет «Новая заметка», 21.10): тёмная
// плавающая плашка над клавиатурой с самым нужным — ассистент, заголовок,
// жирный, чекбокс, список, фото, голос. «+» раскрывает над ней полную
// панель (тот же EditorToolbar, что на десктопе, в тёмном варианте).
export default function MobileEditorToolbar(props: ComponentProps<typeof EditorToolbar>) {
  const { editor, onInsertImage, onOpenRecorder, onOpenAssistant, uploadProgress, aiLoading } = props;
  const [expanded, setExpanded] = useState(false);
  const inset = useKeyboardInset();
  if (!editor) return null;
  const uploading = uploadProgress !== null;

  const btn = (
    title: string,
    onClick: () => void,
    children: React.ReactNode,
    opts?: { active?: boolean; tone?: "brand" | "lime"; disabled?: boolean },
  ) => (
    <button
      type="button"
      title={title}
      aria-label={title}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      disabled={opts?.disabled}
      className={`flex h-11 min-w-0 flex-1 items-center justify-center rounded-xl text-nav-text transition-colors disabled:opacity-40 ${
        opts?.tone === "brand" ? "bg-brand text-white" : opts?.tone === "lime" ? "text-lime" : opts?.active ? "bg-white/15" : "hover:bg-white/10"
      }`}
    >
      {children}
    </button>
  );

  // «Aa»: обычный текст → заголовок 2 → заголовок 3 → обычный текст.
  const cycleHeading = (e: Editor) => {
    if (e.isActive("heading", { level: 2 })) e.chain().focus().toggleHeading({ level: 3 }).run();
    else if (e.isActive("heading", { level: 3 })) e.chain().focus().setParagraph().run();
    else e.chain().focus().toggleHeading({ level: 2 }).run();
  };

  return (
    <div
      className="pointer-events-none absolute inset-x-2.5 z-10 flex flex-col gap-1.5 transition-[bottom] duration-150"
      style={{ bottom: `calc(10px + ${inset}px)` }}
    >
      {expanded && (
        <div className="pointer-events-auto overflow-hidden rounded-2xl bg-nav shadow-nav">
          <EditorToolbar {...props} variant="dark" />
        </div>
      )}
      {/* Кнопки делят ширину поровну (flex-1), а не 44px каждая: на 360px
          восемь штук иначе не влезают, и «+» уезжал за край. */}
      <div className="pointer-events-auto flex h-14 items-center gap-0.5 rounded-2xl bg-nav px-1.5 shadow-nav">
        {onOpenAssistant &&
          btn("Ассистент", onOpenAssistant, aiLoading ? <Spinner size={16} /> : <Sparkles size={18} strokeWidth={2.4} />, { tone: "brand" })}
        {btn("Заголовок", () => cycleHeading(editor), <span className="text-base font-extrabold">Aa</span>, {
          active: editor.isActive("heading"),
        })}
        {btn("Жирный", () => editor.chain().focus().toggleBold().run(), <Bold size={18} strokeWidth={2.6} />, {
          active: editor.isActive("bold"),
        })}
        {btn("Чекбокс", () => editor.chain().focus().toggleTaskList().run(), <ListChecks size={20} strokeWidth={2.2} />, {
          active: editor.isActive("taskList"),
        })}
        {btn("Список", () => editor.chain().focus().toggleBulletList().run(), <List size={20} strokeWidth={2.2} />, {
          active: editor.isActive("bulletList"),
        })}
        {btn("Фото", onInsertImage, uploading ? <Spinner size={16} /> : <ImageIcon size={20} strokeWidth={2.2} />, { disabled: uploading })}
        {onOpenRecorder && btn("Голос", onOpenRecorder, <Mic size={20} strokeWidth={2.2} />, { tone: "lime" })}
        {btn(expanded ? "Скрыть инструменты" : "Ещё инструменты", () => setExpanded((v) => !v), expanded ? <X size={20} strokeWidth={2.4} /> : <Plus size={20} strokeWidth={2.4} />, {
          active: expanded,
        })}
      </div>
    </div>
  );
}
