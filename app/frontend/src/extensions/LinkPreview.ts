import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import LinkPreviewCard from "../components/LinkPreviewCard";

// Карточка ссылки (Slack-style unfurl): вставленная голая ссылка на сайт
// превращается в узел с favicon+заголовком, при наведении — попап с
// картинкой/описанием. В отличие от Video/ResizableImage карточке нужны
// async-подгрузка данных с бэкенда и интерактивный ховер, поэтому рендер —
// не статический renderHTML, а React-компонент через ReactNodeViewRenderer.
// Сериализация в markdown — обычная ссылка с маркером-атрибутом, тот же
// приём, что у Video/ResizableImage: Markdown.configure({html: true}) на
// редакторе разбирает вставленный HTML-блок обратно в DOM при загрузке, а
// parseHTML() здесь его ловит — round-trip без специального формата.
export const LinkPreview = Node.create({
  name: "linkPreview",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      url: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("href"),
        renderHTML: (attrs: { url?: string | null }) => (attrs.url ? { href: attrs.url } : {}),
      },
    };
  },

  parseHTML() {
    // priority выше дефолтных 50: @tiptap/extension-link регистрирует
    // свой mark-правило на a[href] с обычным приоритетом — при равном
    // приоритете ProseMirror выбирает mark-правило вместо нашего node,
    // и вся ссылка молча схлопывается в пустой абзац (реально
    // воспроизведено: после перезагрузки страницы карточка исчезала
    // целиком). Явный приоритет гарантирует, что при наличии
    // data-linkpreview побеждает именно узел, а не marka обычной ссылки.
    return [{ tag: "a[data-linkpreview]", priority: 100 }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["a", mergeAttributes(HTMLAttributes, { "data-linkpreview": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(LinkPreviewCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: { url: string } },
        ) {
          state.write(`<a href="${node.attrs.url.replace(/"/g, "&quot;")}" data-linkpreview></a>`);
          // closeBlock, а не голый write: без него следующий блок (обычный
          // абзац после карточки) слипается с этой строкой без пустой
          // строки-разделителя — по правилам CommonMark сырой HTML-блок
          // без пустой строки после себя жадно поглощает всё, что идёт
          // следом, как часть самого себя.
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
