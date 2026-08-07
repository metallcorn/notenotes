import ImageExtension from "@tiptap/extension-image";

/**
 * @tiptap/extension-image без доп. атрибутов сериализуется в чистый
 * ![]() markdown. Как только заданы width/align, сериализуем в inline
 * <img> — это по-прежнему валидный markdown (спецификация разрешает
 * встроенный HTML), просто способ выразить то, что у ![]() синтаксиса
 * нет. Round-trip (markdown -> редактор -> markdown) проверен отдельно
 * до внедрения — без custom parseHTML/renderHTML/serialize width и align
 * молча терялись бы при первом же сохранении.
 */
export const ResizableImage = ImageExtension.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      // Относительная ширина (%), не пиксели — иначе на другом экране
      // картинка либо теряется мелкой, либо вылезает за контейнер.
      width: {
        default: null,
        parseHTML: (element: HTMLElement) => element.style.width || element.getAttribute("width"),
        renderHTML: (attrs: { width?: string | null }) => (attrs.width ? { style: `width: ${attrs.width}` } : {}),
      },
      align: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("align"),
        renderHTML: (attrs: { align?: string | null }) => (attrs.align ? { align: attrs.align } : {}),
      },
    };
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; esc: (s: string) => string },
          node: { attrs: { src: string; alt?: string | null; title?: string | null; width?: string | null; align?: string | null } },
        ) {
          const { src, alt, title, width, align } = node.attrs;
          if (!width && !align) {
            state.write(
              "![" +
                state.esc(alt || "") +
                "](" +
                src.replace(/[()]/g, "\\$&") +
                (title ? ' "' + title.replace(/"/g, '\\"') + '"' : "") +
                ")",
            );
            return;
          }
          const parts = [`src="${src}"`];
          if (alt) parts.push(`alt="${state.esc(alt)}"`);
          if (width) parts.push(`style="width: ${width}"`);
          if (align) parts.push(`align="${align}"`);
          state.write(`<img ${parts.join(" ")} />`);
        },
        parse: {},
      },
    };
  },
});
