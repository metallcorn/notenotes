import { useRef } from "react";
import type { PointerEvent, MouseEvent } from "react";

// Долгое нажатие на строку (макет «Папки спейса», 21.10: «долгое нажатие
// на папку — переименовать, перенести, удалить»). Два пути, потому что
// браузеры разные: Android Chrome на долгое касание сам шлёт contextmenu,
// iOS Safari — нет, там срабатывает таймер. Оба ставят `fired`, чтобы
// клик, который придёт следом за отпусканием пальца, не открыл папку
// поверх только что показанной шторки.
export function useLongPress(onLongPress: () => void, delay = 450) {
  const timer = useRef<number | null>(null);
  const fired = useRef(false);
  const start = useRef<{ x: number; y: number } | null>(null);

  const clear = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const handlers = {
    onPointerDown: (e: PointerEvent) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      fired.current = false;
      start.current = { x: e.clientX, y: e.clientY };
      clear();
      timer.current = window.setTimeout(() => {
        timer.current = null;
        fired.current = true;
        onLongPress();
      }, delay);
    },
    onPointerMove: (e: PointerEvent) => {
      // Палец поехал — это прокрутка списка, а не удержание.
      if (start.current && Math.hypot(e.clientX - start.current.x, e.clientY - start.current.y) > 10) clear();
    },
    onPointerUp: clear,
    onPointerLeave: clear,
    onPointerCancel: clear,
    onContextMenu: (e: MouseEvent) => {
      e.preventDefault();
      clear();
      if (!fired.current) {
        fired.current = true;
        onLongPress();
      }
    },
  };

  // Обёртка для onClick: после долгого нажатия обычный клик глотается.
  const guard = (fn: () => void) => () => {
    if (fired.current) {
      fired.current = false;
      return;
    }
    fn();
  };

  return { handlers, guard };
}
