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
          open ? "bg-accent text-on-accent" : "text-secondary hover:bg-muted-hover"
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
              className="fixed z-50 w-64 rounded-2xl border bg-surface py-1.5 shadow-lg"
            >
              <button
                onClick={() => run("summarize")}
                className="block min-h-10 w-full px-4 py-2 text-left text-sm font-semibold text-secondary hover:bg-muted"
              >
                Суммаризировать
              </button>
              <button
                onClick={() => run("reformat")}
                className="block min-h-10 w-full px-4 py-2 text-left text-sm font-semibold text-secondary hover:bg-muted"
              >
                Переформатировать
              </button>
              {onOpenAssistant && (
                <button
                  onClick={() => {
                    setOpen(false);
                    onOpenAssistant();
                  }}
                  className="flex w-full items-center gap-1.5 border-t px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
                >
                  <Search size={13} className="text-subtle" />
                  Спросить ассистента
                </button>
              )}
              <div className="border-t px-3 py-1.5">
                <div className="mb-1 text-xs font-medium uppercase tracking-wide text-subtle">Переписать</div>
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {REWRITE_PRESETS.map((p) => (
                    <button
                      key={p}
                      onClick={() => run("rewrite", p.toLowerCase())}
                      className="rounded-full border border-default px-2 py-0.5 text-xs text-secondary hover:bg-muted-hover"
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
                    className="min-w-0 flex-1 h-8 rounded-lg border bg-surface px-2.5 text-xs outline-none"
                  />
                  <button
                    onClick={() => customInstruction.trim() && run("rewrite", customInstruction.trim())}
                    disabled={!customInstruction.trim()}
                    className="shrink-0 h-8 rounded-lg bg-accent px-3 text-xs font-bold text-on-accent disabled:opacity-30"
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
