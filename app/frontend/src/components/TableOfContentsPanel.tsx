import type { Editor } from "@tiptap/core";
import { useEffect, useState } from "react";
import { X } from "lucide-react";

interface Heading {
  pos: number;
  level: number;
  text: string;
}

// До 3 уровня — просьба пользователя: заметки редко нуждаются в более
// глубокой навигации, а более длинный список хуже читается в узкой
// прозрачной панели.
function extractHeadings(editor: Editor): Heading[] {
  const headings: Heading[] = [];
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name === "heading" && node.attrs.level <= 3) {
      headings.push({ pos, level: node.attrs.level, text: node.textContent.trim() });
    }
    return true;
  });
  return headings;
}

// Небольшая полупрозрачная панель слева ПОВЕРХ заметки (не в потоке
// документа и не в скролле контента — родитель фиксирован, см. NoteEditor),
// чтобы визуально не мешала, но давала быстро прыгать по заголовкам.
// Работает и в режиме "Просмотр" (editor смонтирован всегда, см. комментарий
// у EditorContent в NoteEditor.tsx — переключение режима не размонтирует
// его), поэтому листать оглавление можно и в read-only режиме.
export default function TableOfContentsPanel({ editor, onClose }: { editor: Editor | null; onClose: () => void }) {
  const [headings, setHeadings] = useState<Heading[]>(() => (editor ? extractHeadings(editor) : []));

  useEffect(() => {
    if (!editor) return;
    const update = () => setHeadings(extractHeadings(editor));
    update();
    editor.on("update", update);
    return () => {
      editor.off("update", update);
    };
  }, [editor]);

  function goTo(pos: number) {
    if (!editor) return;
    const dom = editor.view.nodeDOM(pos) as HTMLElement | null;
    dom?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-56 max-w-[70vw] p-2">
      <div className="pointer-events-auto flex max-h-full flex-col overflow-hidden rounded-lg border border-slate-200/70 bg-white/75 shadow-sm backdrop-blur-sm">
        <div className="flex shrink-0 items-center justify-between border-b border-slate-200/70 px-2 py-1">
          <span className="text-xs font-medium text-slate-500">Содержание</span>
          <button
            onClick={onClose}
            title="Скрыть содержание"
            className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X size={13} />
          </button>
        </div>
        <div className="overflow-y-auto py-1">
          {headings.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-slate-400">В заметке нет заголовков</p>
          ) : (
            headings.map((h) => (
              <button
                key={h.pos}
                onClick={() => goTo(h.pos)}
                title={h.text || "Без текста"}
                className="block w-full truncate px-2 py-1 text-left text-xs text-slate-600 hover:bg-slate-100"
                style={{ paddingLeft: `${8 + (h.level - 1) * 10}px` }}
              >
                {h.text || "…"}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
