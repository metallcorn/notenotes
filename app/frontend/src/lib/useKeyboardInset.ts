import { useEffect, useState } from "react";

// Высота экранной клавиатуры снизу, в px. Android с
// interactive-widget=resizes-content (index.html) сам сжимает раскладку,
// и тут будет 0; iOS Safari раскладку не трогает — уменьшается только
// visualViewport, и плавающую панель над клавиатурой надо поднимать
// руками на эту разницу.
export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    const vv = typeof window !== "undefined" ? window.visualViewport : null;
    if (!vv) return;
    const update = () => {
      const next = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop));
      // Мелкие дрожания (адресная строка Safari) — не клавиатура.
      setInset(next < 80 ? 0 : next);
    };
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, []);
  return inset;
}
