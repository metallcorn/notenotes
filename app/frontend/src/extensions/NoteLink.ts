import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import NoteLinkCard from "../components/NoteLinkCard";

// Ссылка на другую заметку (ТЗ §7: "ручные, wiki-стиль [[название] или
// прямая ссылка на item"). Инлайн-атом с itemId, тот же приём, что
// ReminderAnchor.ts — id заметки известен уже в момент вставки (её выбрали
// из автокомплита NoteLinkSuggestion.ts), хранить его в узле надёжнее, чем
// перепарсивать текст "[[Название]]" каждый раз: название заметки может
// поменяться, а ссылка должна продолжать вести на ту же заметку.
export interface NoteLinkOptions {
  onOpen: (itemId: string) => void;
}

export const NoteLink = Node.create<NoteLinkOptions>({
  name: "noteLink",
  group: "inline",
  inline: true,
  atom: true,
  draggable: true,

  addOptions() {
    return { onOpen: () => {} };
  },

  addAttributes() {
    return {
      itemId: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-item-id"),
        renderHTML: (attrs: { itemId?: string | null }) => (attrs.itemId ? { "data-item-id": attrs.itemId } : {}),
      },
      title: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-title") ?? element.textContent ?? "",
        renderHTML: (attrs: { title?: string }) => (attrs.title ? { "data-title": attrs.title } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "a[data-note-link]" }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return ["a", mergeAttributes(HTMLAttributes, { "data-note-link": "" }), node.attrs.title || ""];
  },

  addNodeView() {
    return ReactNodeViewRenderer(NoteLinkCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: { write: (s: string) => void }, node: { attrs: { itemId: string | null; title: string } }) {
          const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
          const title = esc(node.attrs.title || "");
          state.write(`<a data-note-link data-item-id="${node.attrs.itemId ?? ""}" data-title="${title}">${title}</a>`);
        },
        parse: {},
      },
    };
  },
});
