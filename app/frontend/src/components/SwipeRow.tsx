import { useRef, useState, type PointerEvent, type ReactNode } from "react";

// Карточка со свайпом влево (макет «Активность», 21.10: «смахни карточку
// влево — „Завтра“ или „Сделано“»). Под карточкой лежат кнопки, карточка
// едет за пальцем; отпустил дальше половины — открывается, иначе
// возвращается. Только касания: мышью карточки тянут drag-and-drop'ом
// (lib/dragItem.ts), и с ним свайп конфликтовал бы.
export default function SwipeRow({
  actions,
  children,
  className = "",
}: {
  actions: { label: string; onClick: () => void; tone?: "dark" | "lime" | "danger" | "brand"; icon?: ReactNode }[];
  children: ReactNode;
  className?: string;
}) {
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; y: number; offset: number } | null>(null);
  const axis = useRef<"x" | "y" | null>(null);
  const width = actions.length * 76;

  const onPointerDown = (e: PointerEvent) => {
    if (e.pointerType !== "touch") return;
    start.current = { x: e.clientX, y: e.clientY, offset };
    axis.current = null;
  };
  const onPointerMove = (e: PointerEvent) => {
    if (!start.current) return;
    const dx = e.clientX - start.current.x;
    const dy = e.clientY - start.current.y;
    if (axis.current === null) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      axis.current = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
      if (axis.current === "x") setDragging(true);
    }
    if (axis.current !== "x") return;
    const next = Math.max(-width, Math.min(0, start.current.offset + dx));
    setOffset(next);
  };
  const finish = () => {
    if (!start.current) return;
    start.current = null;
    setDragging(false);
    if (axis.current === "x") setOffset(offset < -width / 2 ? -width : 0);
    axis.current = null;
  };
  const tones: Record<string, string> = {
    dark: "bg-nav text-nav-text",
    lime: "bg-lime text-on-lime",
    danger: "bg-danger text-white",
    brand: "bg-brand text-white",
  };

  return (
    <div className={`relative overflow-hidden rounded-2xl ${className}`}>
      <div className="absolute inset-y-0 right-0 flex" style={{ width }} aria-hidden={offset === 0}>
        {actions.map((a) => (
          <button
            key={a.label}
            type="button"
            tabIndex={offset === 0 ? -1 : 0}
            onClick={() => {
              setOffset(0);
              a.onClick();
            }}
            className={`flex w-[76px] flex-col items-center justify-center gap-1 text-xs font-extrabold ${tones[a.tone ?? "dark"]}`}
          >
            {a.icon}
            {a.label}
          </button>
        ))}
      </div>
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finish}
        onPointerCancel={finish}
        onClickCapture={(e) => {
          // Открытые кнопки: тап по самой карточке закрывает их, а не
          // открывает заметку.
          if (offset !== 0) {
            e.stopPropagation();
            setOffset(0);
          }
        }}
        style={{ transform: `translateX(${offset}px)`, transition: dragging ? "none" : "transform 180ms ease-out", touchAction: "pan-y" }}
        className="relative"
      >
        {children}
      </div>
    </div>
  );
}
