import ImageExtension from "@tiptap/extension-image";
import { ReactNodeViewRenderer } from "@tiptap/react";
import ResizableImageView from "../components/ResizableImageView";

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
      // Реальная жалоба: телефон снял горизонтально, в заметке читать
      // невозможно — поворот должен СОХРАНЯТЬСЯ (не просто разворот на
      // время просмотра, как в полноэкранном ImageLightbox.tsx — там он
      // эфемерный, тут это правка самой заметки). 0/90/180/270 — тех же
      // символов достаточно, произвольный угол не нужен, как в Telegram.
      rotation: {
        default: 0,
        parseHTML: (element: HTMLElement) => Number(element.getAttribute("data-rotate")) || 0,
        renderHTML: (attrs: { rotation?: number }) => (attrs.rotation ? { "data-rotate": String(attrs.rotation) } : {}),
      },
    };
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; esc: (s: string) => string },
          node: {
            attrs: {
              src: string;
              alt?: string | null;
              title?: string | null;
              width?: string | null;
              align?: string | null;
              rotation?: number;
            };
          },
        ) {
          const { src, alt, title, width, align, rotation } = node.attrs;
          if (!width && !align && !rotation) {
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
          if (rotation) parts.push(`data-rotate="${rotation}"`);
          state.write(`<img ${parts.join(" ")} />`);
        },
        parse: {},
      },
    };
  },

  // NodeView, не голый renderHTML — нужен оверлей "распознаём…" прямо
  // поверх превью, пока фоновая обработка (vision.py) не заменит соседний
  // плейсхолдер-параграф на готовый результат (см. ResizableImageView.tsx).
  addNodeView() {
    return ReactNodeViewRenderer(ResizableImageView);
  },
});
