import type { Editor } from "@tiptap/core";

// Тот же набор ширин, что у ImageToolbar.tsx — реальная просьба: видео
// должно регулироваться по ширине так же, как картинка.
const WIDTHS = [
  { label: "Маленькая", value: "25%" },
  { label: "Средняя", value: "50%" },
  { label: "Крупная", value: "75%" },
];

export default function VideoToolbar({ editor }: { editor: Editor }) {
  const attrs = editor.getAttributes("video") as { width?: string | null };

  function setWidth(width: string | null) {
    editor.chain().focus().updateAttributes("video", { width }).run();
  }

  return (
    <div className="mx-4 mb-1 flex flex-wrap items-center gap-2 rounded-2xl bg-brand-soft px-3 py-1.5 text-xs font-bold text-brand-text">
      <span className="text-subtle">Видео:</span>
      <div className="flex gap-0.5">
        {WIDTHS.map((w) => (
          <button
            key={w.value}
            onClick={() => setWidth(attrs.width === w.value ? null : w.value)}
            className={`rounded px-1.5 py-0.5 ${
              attrs.width === w.value ? "bg-accent text-on-accent" : "bg-surface text-secondary hover:bg-muted-hover"
            }`}
          >
            {w.label}
          </button>
        ))}
        <button
          onClick={() => setWidth(null)}
          className={`rounded px-1.5 py-0.5 ${
            !attrs.width ? "bg-accent text-on-accent" : "bg-surface text-secondary hover:bg-muted-hover"
          }`}
        >
          Оригинал
        </button>
      </div>
    </div>
  );
}
