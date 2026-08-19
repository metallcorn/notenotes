import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import TableEmbedCard from "../components/TableEmbedCard";

// Живая rich-таблица (material_type="table"), встроенная прямо в текст
// заметки — узел хранит только tableId, сама таблица остаётся отдельным
// item'ом (своя история версий, свой WS, свои LLM-тулы). Заметка ссылается
// на неё, а не владеет ей: удаление этого узла из текста таблицу не удаляет,
// и одна и та же таблица может быть встроена в несколько заметок сразу —
// TableEmbedCard.tsx у каждой копии синкается по tableId независимо.
// Тот же round-trip приём, что у DocumentAttachment/UrlCheckAttachment —
// сырой HTML-div с data-атрибутом прямо в сохраняемом markdown.
export function serializeTableEmbed(tableId: string): string {
  return `<div data-table-embed data-table-id="${tableId}"></div>`;
}

export const TableEmbed = Node.create({
  name: "tableEmbed",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      tableId: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-table-id"),
        renderHTML: (attrs: { tableId?: string | null }) =>
          attrs.tableId ? { "data-table-id": attrs.tableId } : {},
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-table-embed]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-table-embed": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(TableEmbedCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: { tableId: string } },
        ) {
          state.write(serializeTableEmbed(node.attrs.tableId));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
