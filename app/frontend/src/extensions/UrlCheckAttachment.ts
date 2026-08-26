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
// Реальный найденный баг: если attrs.id узла в какой-то момент оказался
// null/undefined (например, гонка при вставке или сбой Yjs-синка —
// возможные причины не подтверждены, но след виден по факту), эта функция
// слепо подставляла его в шаблонную строку — JS сериализует null в
// ЛИТЕРАЛЬНУЮ строку "null", неотличимую от настоящего id на вид. При
// следующем автосохранении это НАВСЕГДА запекалось в markdown заметки —
// плашка переставала находить виджет («перестала работать»), а без
// сохранённого настоящего id восстановить исходный URL/поля уже нечем.
// renderHTML ниже уже был защищён (`attrs.id ? {...} : {}`) — сериализатор
// в markdown такой же проверки не имел, отсюда асимметрия. Теперь при
// отсутствующем id тег пишется БЕЗ атрибута (round-trip обратно даёт
// attrs.id === null — честное "виджет не привязан", не похожий на
// настоящий id мусор).
export function serializeUrlCheck(id: string | null | undefined): string {
  return id ? `<div data-url-check data-url-check-id="${id}"></div>` : `<div data-url-check></div>`;
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
          node: { attrs: { id: string | null } },
        ) {
          state.write(serializeUrlCheck(node.attrs.id));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
