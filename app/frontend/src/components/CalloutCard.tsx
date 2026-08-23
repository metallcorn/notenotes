import { useState } from "react";
import { NodeViewContent, NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { AlertOctagon, AlertTriangle, ChevronDown, ChevronRight, Info, Lightbulb } from "lucide-react";
import type { CalloutVariant } from "../extensions/Callout";

// Один компонент на все пять вариантов (spoiler/hint/info/warning/danger) —
// см. Callout.ts. Спойлер сворачиваемый (плюс редактируемый заголовок) —
// принципиально другая вещь, не просто ещё один цвет: у него нет
// фиксированной подписи и типа, переключать там нечего. Остальные четыре
// (hint/info/warning/danger) — цветные плашки как в Confluence, тип
// переключается прямо на блоке через иконку в углу, а не при вставке.
const ADMONITION_VARIANTS = ["hint", "info", "warning", "danger"] as const;

const VARIANT_STYLE: Record<CalloutVariant, { border: string; bg: string; icon: string; label: string }> = {
  spoiler: { border: "border-slate-300", bg: "bg-slate-50", icon: "text-slate-500", label: "Спойлер" },
  hint: { border: "border-emerald-300", bg: "bg-emerald-50", icon: "text-emerald-600", label: "Совет" },
  info: { border: "border-blue-300", bg: "bg-blue-50", icon: "text-blue-600", label: "Информация" },
  warning: { border: "border-amber-300", bg: "bg-amber-50", icon: "text-amber-600", label: "Важно" },
  danger: { border: "border-red-300", bg: "bg-red-50", icon: "text-red-600", label: "Опасно" },
};

function VariantIcon({ variant, size = 15, className }: { variant: CalloutVariant; size?: number; className?: string }) {
  if (variant === "hint") return <Lightbulb size={size} className={className} />;
  if (variant === "warning") return <AlertTriangle size={size} className={className} />;
  if (variant === "danger") return <AlertOctagon size={size} className={className} />;
  return <Info size={size} className={className} />;
}

function VariantSwitcher({ variant, onPick }: { variant: CalloutVariant; onPick: (v: CalloutVariant) => void }) {
  const [open, setOpen] = useState(false);
  const style = VARIANT_STYLE[variant] ?? VARIANT_STYLE.info;

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        title="Сменить тип плашки"
        contentEditable={false}
        className={`flex items-center ${style.icon} hover:opacity-70`}
      >
        <VariantIcon variant={variant} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-50 mt-1 flex gap-0.5 rounded border bg-white p-1 shadow-lg">
            {ADMONITION_VARIANTS.map((v) => (
              <button
                key={v}
                title={VARIANT_STYLE[v].label}
                onClick={() => {
                  onPick(v);
                  setOpen(false);
                }}
                className={`flex h-7 w-7 items-center justify-center rounded ${v === variant ? VARIANT_STYLE[v].bg : "hover:bg-slate-100"} ${VARIANT_STYLE[v].icon}`}
              >
                <VariantIcon variant={v} size={14} />
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function CalloutCard({ node, updateAttributes }: NodeViewProps) {
  const { variant, title, open } = node.attrs as { variant: CalloutVariant; title: string | null; open: boolean };
  const style = VARIANT_STYLE[variant] ?? VARIANT_STYLE.info;
  const isSpoiler = variant === "spoiler";

  return (
    <NodeViewWrapper as="div" className={`my-1 rounded border ${style.border} ${style.bg}`}>
      <div data-drag-handle draggable className="flex items-center gap-1.5 px-2.5 py-1.5">
        {isSpoiler ? (
          <button
            onClick={() => updateAttributes({ open: !open })}
            title={open ? "Свернуть" : "Развернуть"}
            className="flex shrink-0 items-center text-slate-500 hover:text-slate-700"
            contentEditable={false}
          >
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <VariantSwitcher variant={variant} onPick={(v) => updateAttributes({ variant: v })} />
        )}
        {isSpoiler ? (
          <input
            value={title ?? ""}
            onChange={(e) => updateAttributes({ title: e.target.value })}
            placeholder="Заголовок спойлера"
            contentEditable={false}
            className="min-w-0 flex-1 bg-transparent text-sm font-medium text-slate-700 outline-none placeholder:text-slate-400"
          />
        ) : (
          <span className={`text-sm font-medium ${style.icon}`}>{style.label}</span>
        )}
      </div>
      <NodeViewContent
        className={`px-3 pb-2.5 pt-0.5 text-sm [&>:first-child]:mt-0 [&>:last-child]:mb-0 ${isSpoiler && !open ? "hidden" : ""}`}
      />
    </NodeViewWrapper>
  );
}
