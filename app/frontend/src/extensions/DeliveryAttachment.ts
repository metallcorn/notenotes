import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import DeliveryWidgetCard from "../components/DeliveryWidgetCard";

// Постоянный виджет отслеживания доставки в заметке (по образцу
// UrlCheckAttachment). В content лежит только data-delivery-id —
// перевозчик/номер/результат живут в delivery_widgets на бэкенде
// (models.py::DeliveryWidget) и подтягиваются картой при монтировании
// (routers/delivery_widgets.py). Вставляется ассистентом
// (tools/track_delivery.py::insert_delivery_block).
export function serializeDelivery(id: string): string {
  return `<div data-delivery data-delivery-id="${id}"></div>`;
}

export const DeliveryAttachment = Node.create({
  name: "delivery",
  group: "block",
  atom: true,
  // НЕ draggable: true. Реальный найденный баг: draggable — атрибут узла
  // (Node.create), TipTap ставит его на ВНЕШНЮЮ обёртку NodeView САМ, ещё
  // до всего, что рендерит React-компонент — предыдущая попытка починить
  // "клик по ссылке открывает две вкладки" убирала draggable-проп у
  // NodeViewWrapper внутри DeliveryWidgetCard.tsx, но это другой, более
  // внутренний слой, отдельный от ЭТОГО атрибута узла — сам баг не
  // трогала. Без явного data-drag-handle где-то внутри карточки ВЕСЬ
  // wrapper становится зоной перетаскивания по умолчанию (см. DocumentAttachment.ts/
  // TicketAttachment.ts — там drag-handle сужен до отдельной строки без
  // ссылки внутри; здесь ссылка "Трекинг" — часть всей карточки, сузить
  // некуда) — конфликтует с нативным "перетащить ссылку" браузера,
  // изредка открывая клик сразу в двух вкладках.


  addAttributes() {
    return {
      id: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-delivery-id"),
        renderHTML: (attrs: { id?: string | null }) => (attrs.id ? { "data-delivery-id": attrs.id } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-delivery]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-delivery": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(DeliveryWidgetCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: { id: string } },
        ) {
          state.write(serializeDelivery(node.attrs.id));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
