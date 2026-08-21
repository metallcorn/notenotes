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
  draggable: true,

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
