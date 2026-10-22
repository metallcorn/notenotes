import { useRef, useState, type PointerEvent } from "react";

// Перетаскивание строк вверх/вниз пальцем или мышью за «ручку» (шторка
// «Спейсы»: владелец хочет утащить редкий сейф вниз). Порядок считается по
// середине строк, подтверждается при отпускании.
export function useDragReorder<T extends { id: string }>(items: T[], onReorder: (ids: string[]) => void) {
  const [order, setOrder] = useState<string[] | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const rows = useRef(new Map<string, HTMLElement>());
  const pointerId = useRef<number | null>(null);

  const current = order ? order.map((id) => items.find((i) => i.id === id)).filter((x): x is T => !!x) : items;

  const register = (id: string) => (el: HTMLElement | null) => {
    if (el) rows.current.set(id, el);
    else rows.current.delete(id);
  };

  const handle = (id: string) => ({
    onPointerDown: (e: PointerEvent) => {
      e.preventDefault();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      pointerId.current = e.pointerId;
      setDraggingId(id);
      setOrder(items.map((i) => i.id));
    },
    onPointerMove: (e: PointerEvent) => {
      if (pointerId.current !== e.pointerId || !draggingId) return;
      const y = e.clientY;
      setOrder((prev) => {
        const ids = prev ?? items.map((i) => i.id);
        const from = ids.indexOf(draggingId);
        let to = from;
        ids.forEach((other, index) => {
          if (other === draggingId) return;
          const r = rows.current.get(other)?.getBoundingClientRect();
          if (!r) return;
          const mid = r.top + r.height / 2;
          if (index < from && y < mid) to = Math.min(to, index);
          if (index > from && y > mid) to = Math.max(to, index);
        });
        if (to === from) return ids;
        const next = ids.slice();
        next.splice(from, 1);
        next.splice(to, 0, draggingId);
        return next;
      });
    },
    onPointerUp: () => {
      if (!draggingId) return;
      pointerId.current = null;
      setDraggingId(null);
      if (order && order.join() !== items.map((i) => i.id).join()) onReorder(order);
      setOrder(null);
    },
    onPointerCancel: () => {
      pointerId.current = null;
      setDraggingId(null);
      setOrder(null);
    },
    style: { touchAction: "none" as const },
  });

  return { items: current, draggingId, register, handle };
}
