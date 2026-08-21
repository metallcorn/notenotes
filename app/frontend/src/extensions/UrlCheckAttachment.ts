import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import UrlCheckCard from "../components/UrlCheckCard";

// Виджет «Проверить по ссылке» — GET по сохранённому URL, показывает
// выбранные поля из ответа + кнопку «Обновить». Вставляется только
// ассистентом (tools/url_check.py::insert_url_check_block). В content
// заметки лежит только id — url/поля/заголовки авторизации/результат
// последнего запроса живут в UrlCheckWidget на бэкенде (models.py) и
// подтягиваются картой при монтировании (routers/url_checks.py), не
// сериализуются тут вообще. Так «Обновить» не гоняет блоб ответа (до
// 512 КБ) через Yjs/ItemVersion на каждый клик — только один GET/POST.
export function serializeUrlCheck(id: string): string {
  return `<div data-url-check data-url-check-id="${id}"></div>`;
}

export const UrlCheckAttachment = Node.create({
  name: "urlCheck",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      id: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-url-check-id"),
        renderHTML: (attrs: { id?: string | null }) => (attrs.id ? { "data-url-check-id": attrs.id } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-url-check]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-url-check": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(UrlCheckCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: { id: string } },
        ) {
          state.write(serializeUrlCheck(node.attrs.id));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
