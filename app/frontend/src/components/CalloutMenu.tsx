import { useState } from "react";
import type { Editor } from "@tiptap/core";
import { AlertOctagon, AlertTriangle, ChevronDown, Info, Lightbulb, MessageSquare } from "lucide-react";
import type { CalloutVariant } from "../extensions/Callout";

// Тот же дропдаун-паттерн, что ExportMenu.tsx — реальный запрос: слэш-
// команды (/спойлер, /совет...) уже есть, но кнопки на панели форматирования
// не было вообще, хотя у "Цитата"/"Блок кода" рядом она есть. Один пункт
// меню на каждый из пяти вариантов callout, вместо пяти отдельных кнопок
// (панель и так длинная).
const ITEMS: { variant: CalloutVariant; label: string; icon: typeof Info }[] = [
  { variant: "spoiler", label: "Спойлер", icon: MessageSquare },
  { variant: "hint", label: "Совет", icon: Lightbulb },
  { variant: "info", label: "Информация", icon: Info },
  { variant: "warning", label: "Важно", icon: AlertTriangle },
  { variant: "danger", label: "Опасно", icon: AlertOctagon },
];

export default function CalloutMenu({ editor }: { editor: Editor }) {
  const [open, setOpen] = useState(false);

  function insert(variant: CalloutVariant) {
    setOpen(false);
    const attrs = variant === "spoiler" ? { variant, open: true } : { variant };
    editor.chain().focus().insertContent({ type: "callout", attrs, content: [{ type: "paragraph" }] }).run();
  }

  return (
    <div className="relative">
      <button
        type="button"
        title="Спойлер / плашка"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 items-center gap-0.5 rounded px-1 text-slate-600 hover:bg-slate-100"
      >
        <MessageSquare size={16} />
        <ChevronDown size={12} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-50 mt-1 w-44 rounded border bg-white py-1 shadow-lg">
            {ITEMS.map(({ variant, label, icon: Icon }) => (
              <button
                key={variant}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => insert(variant)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
              >
                <Icon size={14} className="shrink-0 text-slate-400" />
                {label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
