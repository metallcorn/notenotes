import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

// Реальная жалоба: во время фоновой обработки загрузки (OCR/расшифровка/
// vision) плейсхолдер "⏳ ... обрабатывается…" — обычный текст, ничем не
// выделен, пользователь не понимает, что что-то вообще происходит фоном.
// Чисто визуальная подсветка через ProseMirror-декорацию (не узел/марка,
// не трогает сериализацию в markdown вообще) — backend ищет и заменяет
// именно этот текст буквальным строковым replace (vision.py/
// transcription.py/pdf_processing.py placeholder_text()), а декорация не
// часть документа, только временное оформление во ВЬЮ.
const PLACEHOLDER_RE = /⏳[^\n]*обрабатывается…/g;

export const ProcessingPlaceholder = Extension.create({
  name: "processingPlaceholder",

  addProseMirrorPlugins() {
    const key = new PluginKey("processingPlaceholder");
    return [
      new Plugin({
        key,
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];
            state.doc.descendants((node, pos) => {
              if (!node.isText || !node.text) return;
              for (const match of node.text.matchAll(PLACEHOLDER_RE)) {
                const from = pos + (match.index ?? 0);
                const to = from + match[0].length;
                decorations.push(
                  Decoration.inline(from, to, { class: "processing-placeholder" }),
                );
              }
            });
            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});
