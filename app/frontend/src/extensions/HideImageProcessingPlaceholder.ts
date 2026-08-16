import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

// Плейсхолдер "⏳ Описание изображения {id} обрабатывается…" (NoteEditor.tsx,
// insertImageAt) — точная строка, по которой backend ищет и заменяет текст
// на готовый результат (vision.py::_replace_in_referencing_items). Убрать
// её из документа нельзя (замена не найдёт, что менять), но показывать её
// пользователю отдельным абзацем под картинкой больше не нужно — с тех пор
// как появился оверлей прямо на превью (ResizableImageView.tsx), эта
// строка ниже была бы дублем. Decoration только СКРЫВАЕТ узел из DOM, не
// трогая сам документ/сериализацию.
const IMAGE_PLACEHOLDER_RE = /^⏳ Описание изображения [0-9a-f-]{36} обрабатывается…$/;

export const HideImageProcessingPlaceholder = Extension.create({
  name: "hideImageProcessingPlaceholder",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("hideImageProcessingPlaceholder"),
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];
            state.doc.descendants((node, pos) => {
              if (node.type.name === "paragraph" && IMAGE_PLACEHOLDER_RE.test(node.textContent)) {
                decorations.push(
                  Decoration.node(pos, pos + node.nodeSize, { class: "image-processing-placeholder-hidden" }),
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
