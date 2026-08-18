import { useRef } from "react";

// Одна и та же полоска между панелями — и кнопка сворачивания (клик), и
// граница ресайза (тянешь мышью). Различаем по факту движения курсора
// между pointerdown и pointerup: если сдвинулось больше нескольких
// пикселей — это был ресайз, onToggle не вызываем (тот же паттерн, что
// в NoteAssistantModal.tsx/RecordingPanel.tsx для тамошнего ресайза, но
// там ручка ресайза отдельная от кнопки — здесь места в сайдбаре под
// два элемента подряд нет, реальная жалоба на тесноту панели).
export function useResizablePanel({
  width,
  collapsed,
  min,
  max,
  onResize,
  onToggle,
}: {
  width: number;
  collapsed: boolean;
  min: number;
  max: number;
  onResize: (next: number) => void;
  onToggle: () => void;
}) {
  const drag = useRef({ startX: 0, startWidth: 0, moved: false });

  function onPointerDown(e: React.PointerEvent<HTMLButtonElement>) {
    drag.current = { startX: e.clientX, startWidth: width, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent<HTMLButtonElement>) {
    if (collapsed) return;
    const dx = e.clientX - drag.current.startX;
    if (Math.abs(dx) > 3) drag.current.moved = true;
    if (!drag.current.moved) return;
    onResize(Math.min(max, Math.max(min, drag.current.startWidth + dx)));
  }
  function onPointerUp(e: React.PointerEvent<HTMLButtonElement>) {
    e.currentTarget.releasePointerCapture(e.pointerId);
    if (!drag.current.moved) onToggle();
  }

  return { onPointerDown, onPointerMove, onPointerUp };
}
