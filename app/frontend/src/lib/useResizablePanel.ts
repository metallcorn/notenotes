import { useRef } from "react";

// Реальный найденный баг: pointermove у браузера срабатывает просто при
// наведении курсора на элемент, независимо от того, зажата ли кнопка —
// без явного флага "идёт перетаскивание" ресайз запускался от одного
// ховера мышкой над полоской (реальная жалоба). drag.active выставляется
// только в pointerdown и снимается в pointerup — onPointerMove до/после
// перетаскивания не делает вообще ничего.
export function useResizeHandle({
  width,
  collapsed,
  min,
  max,
  onResize,
}: {
  width: number;
  collapsed: boolean;
  min: number;
  max: number;
  onResize: (next: number) => void;
}) {
  const drag = useRef({ active: false, startX: 0, startWidth: 0 });

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (collapsed) return;
    drag.current = { active: true, startX: e.clientX, startWidth: width };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!drag.current.active) return;
    const dx = e.clientX - drag.current.startX;
    onResize(Math.min(max, Math.max(min, drag.current.startWidth + dx)));
  }
  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    if (!drag.current.active) return;
    drag.current.active = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  }

  return { onPointerDown, onPointerMove, onPointerUp };
}
