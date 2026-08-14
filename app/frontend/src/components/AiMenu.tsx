import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles, Search } from "lucide-react";
import Spinner from "./Spinner";

export type AiAction = "summarize" | "reformat" | "rewrite";

const REWRITE_PRESETS = ["Короче", "Проще", "Формальнее", "Живее"];

export default function AiMenu({
  onAction,
  onOpenAssistant,
  loading,
  disabled,
  align = "left",
}: {
  onAction: (action: AiAction, instruction?: string) => void;
  // Реальный запрос: "выделил название заведения — хочу, чтобы ассистент
  // нашёл его и предложил обогатить заметку", не просто переформулировал
  // существующий текст (для этого уже есть остальные пункты меню). В
  // отличие от summarize/reformat/rewrite это не текстовое преобразование
  // (aiTransform, без тулов) — открывает полноценный мини-чат с ассистентом
  // (NoteAssistantModal.tsx, тулы web_search/search_base и т.п.), поэтому
  // отдельный колбэк, не ещё один AiAction.
  onOpenAssistant?: () => void;
  loading: boolean;
  disabled?: boolean;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const [customInstruction, setCustomInstruction] = useState("");
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  // Кнопка часто живёт внутри панели инструментов с overflow-x-auto
  // (нужен для горизонтальной прокрутки на мобиле) — а по спецификации CSS
  // overflow-x, отличный от visible, молча превращает overflow-y тоже в
  // auto, так что выпадающее меню обрезается по высоте контейнера панели и
  // становится невидимым, хотя технически существует в DOM (реальная
  // жалоба: "кнопка ИИ не работает" — на самом деле работала, просто меню
  // было обрезано). Портал в document.body с вычисленными координатами
  // обходит любые overflow/z-index предков целиком.
  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const width = 256; // w-64
    setPosition({
      top: rect.bottom + 4,
      left: align === "right" ? rect.right - width : rect.left,
    });
  }, [open, align]);

  function run(action: AiAction, instruction?: string) {
    setOpen(false);
    setCustomInstruction("");
    onAction(action, instruction);
  }

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        title="ИИ"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled || loading}
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded disabled:opacity-30 ${
          open ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
        }`}
      >
        {loading ? <Spinner size={16} /> : <Sparkles size={16} />}
      </button>
      {open &&
        position &&
        createPortal(
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div
              style={{ top: position.top, left: position.left }}
              className="fixed z-50 w-64 rounded border bg-white py-1 shadow-lg"
            >
              <button
                onClick={() => run("summarize")}
                className="block w-full px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
              >
                Суммаризировать
              </button>
              <button
                onClick={() => run("reformat")}
                className="block w-full px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
              >
                Переформатировать
              </button>
              {onOpenAssistant && (
                <button
                  onClick={() => {
                    setOpen(false);
                    onOpenAssistant();
                  }}
                  className="flex w-full items-center gap-1.5 border-t px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
                >
                  <Search size={13} className="text-slate-400" />
                  Спросить ассистента
                </button>
              )}
              <div className="border-t px-3 py-1.5">
                <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">Переписать</div>
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {REWRITE_PRESETS.map((p) => (
                    <button
                      key={p}
                      onClick={() => run("rewrite", p.toLowerCase())}
                      className="rounded-full border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      {p}
                    </button>
                  ))}
                </div>
                <div className="flex gap-1">
                  <input
                    value={customInstruction}
                    onChange={(e) => setCustomInstruction(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && customInstruction.trim()) run("rewrite", customInstruction.trim());
                    }}
                    placeholder="Свой вариант…"
                    className="min-w-0 flex-1 rounded border px-2 py-1 text-xs"
                  />
                  <button
                    onClick={() => customInstruction.trim() && run("rewrite", customInstruction.trim())}
                    disabled={!customInstruction.trim()}
                    className="shrink-0 rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-30"
                  >
                    ОК
                  </button>
                </div>
              </div>
            </div>
          </>,
          document.body,
        )}
    </div>
  );
}
