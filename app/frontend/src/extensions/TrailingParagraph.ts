import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";

// Реальный критичный баг: если заметка заканчивается атом-узлом (картинка,
// вложенный файл, билет — что угодно не-параграф), поставить курсор ПОСЛЕ
// него и начать печатать было невозможно — ProseMirror не создаёt
// текстовую позицию сразу за нередактируемым атомом, если дальше в
// документе ничего нет. Раньше это маскировалось тем, что почти любая
// вставка сопровождалась соседним параграфом-плейсхолдером ("⏳ ...
// обрабатывается…") — теперь, когда карточка файла вставляется сама по
// себе (DocumentAttachmentCard, processing-флаг вместо отдельного
// параграфа), баг стал заметен на каждой такой заметке.
// appendTransaction — гарантирует ПОСЛЕ любого изменения документа, что
// последний узел — параграф; если нет, дописывает пустой. Тот же паттерн,
// что официальное решение TipTap-сообщества для этой же проблемы.
export const TrailingParagraph = Extension.create({
  name: "trailingParagraph",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("trailingParagraph"),
        appendTransaction: (_transactions, _oldState, newState) => {
          const { doc, schema } = newState;
          const lastNode = doc.lastChild;
          if (!lastNode || lastNode.type.name === "paragraph" || !schema.nodes.paragraph) {
            return null;
          }
          return newState.tr.insert(doc.content.size, schema.nodes.paragraph.create());
        },
      }),
    ];
  },
});
