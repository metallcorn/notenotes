import { useRef, useState, type CSSProperties, type PointerEvent } from "react";

// Перетаскивание строк вверх/вниз пальцем или мышью за «ручку» (шторка
// «Спейсы»: владелец хочет утащить редкий сейф вниз).
//
// Первая версия переставляла строки в DOM прямо во время движения —
// получалось дёргано (строка прыгала сразу на целую позицию, а середины
// соседей после каждой перестановки уезжали, и расчёт шёл по кругу), а
// при отпускании порядок брался из устаревшего состояния и список
// отскакивал назад. Теперь порядок DOM во время перетаскивания не
// меняется: тянутая строка едет за указателем (translateY), соседи
// плавно сдвигаются на её высоту, целевая позиция считается по
// снимку геометрии, снятому в момент захвата. Перестановка — один раз,
// при отпускании, из ref (всегда актуален, в отличие от state).
type Drag = { id: string; from: number; to: number; dy: number; height: number; gap: number };

export function useDragReorder<T extends { id: string }>(items: T[], onReorder: (ids: string[]) => void) {
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const rows = useRef(new Map<string, HTMLElement>());
  const rects = useRef<{ id: string; mid: number }[]>([]);
  const startY = useRef(0);

  const update = (next: Drag | null) => {
    dragRef.current = next;
    setDrag(next);
  };

  const register = (id: string) => (el: HTMLElement | null) => {
    if (el) rows.current.set(id, el);
    else rows.current.delete(id);
  };

  const handle = (id: string) => ({
    onPointerDown: (e: PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      const snapshot = items
        .map((i) => {
          const r = rows.current.get(i.id)?.getBoundingClientRect();
          return r ? { id: i.id, top: r.top, height: r.height, mid: r.top + r.height / 2 } : null;
        })
        .filter((x): x is { id: string; top: number; height: number; mid: number } => !!x);
      rects.current = snapshot;
      const from = snapshot.findIndex((r) => r.id === id);
      if (from < 0) return;
      const gap = snapshot.length > 1 ? Math.max(0, snapshot[1].top - (snapshot[0].top + snapshot[0].height)) : 8;
      startY.current = e.clientY;
      update({ id, from, to: from, dy: 0, height: snapshot[from].height, gap });
    },
    onPointerMove: (e: PointerEvent) => {
      const d = dragRef.current;
      if (!d || d.id !== id) return;
      const dy = e.clientY - startY.current;
      const y = rects.current[d.from].mid + dy;
      // Целевая позиция — сколько ДРУГИХ строк (по снимку) лежит выше
      // текущей середины тянутой строки.
      let to = 0;
      for (const r of rects.current) {
        if (r.id === id) continue;
        if (y > r.mid) to++;
      }
      update({ ...d, dy, to });
    },
    onPointerUp: (e: PointerEvent) => {
      e.stopPropagation();
      const d = dragRef.current;
      if (!d || d.id !== id) return;
      update(null);
      if (d.to !== d.from) {
        const ids = items.map((i) => i.id);
        ids.splice(d.from, 1);
        ids.splice(d.to, 0, d.id);
        onReorder(ids);
      }
    },
    onPointerCancel: () => update(null),
    style: { touchAction: "none" as const },
  });

  // Стиль строки на время перетаскивания: тянутая едет за указателем,
  // соседи между старой и новой позицией сдвигаются на её высоту.
  const styleFor = (id: string): CSSProperties => {
    if (!drag) return { transition: "transform 160ms ease" };
    if (id === drag.id) return { transform: `translateY(${drag.dy}px)`, zIndex: 10, position: "relative", transition: "none" };
    const index = items.findIndex((i) => i.id === id);
    const step = drag.height + drag.gap;
    let shift = 0;
    if (drag.from < drag.to && index > drag.from && index <= drag.to) shift = -step;
    if (drag.from > drag.to && index >= drag.to && index < drag.from) shift = step;
    return { transform: `translateY(${shift}px)`, transition: "transform 160ms ease" };
  };

  return { draggingId: drag?.id ?? null, register, handle, styleFor };
}
