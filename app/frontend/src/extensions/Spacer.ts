import { Node, mergeAttributes } from "@tiptap/core";

// Явный блок визуального отступа между абзацами (/меню → «Отступ»).
// Причина существования: несколько пустых <p> подряд, которые пользователь
// получает просто нажатием Enter, не переживают хранение в Markdown —
// CommonMark не различает одну и несколько пустых строк подряд, это всегда
// один и тот же разделитель абзацев, поэтому "лишние" пустые абзацы
// схлопываются при следующем открытии заметки (round-trip через
// markdown-it в MarkdownParser). Спейсер — атомарный блочный узел, а не
// пустой параграф, поэтому в markdown он не пустая строка, а свой тег и
// не схлопывается. Тот же приём round-trip через html_block, что у
// DocumentAttachment/LinkPreview (markdown-it с html:true пропускает такой
// тег как есть).
export const Spacer = Node.create({
  name: "spacer",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  parseHTML() {
    return [{ tag: "div[data-spacer]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-spacer": "", class: "note-spacer" })];
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: { write: (s: string) => void; closeBlock: (node: unknown) => void }, node: unknown) {
          state.write("<div data-spacer></div>");
          state.closeBlock(node);
        },
        parse: {
          // разбирается стандартным markdown-it html_block + parseHTML выше
        },
      },
    };
  },
});
