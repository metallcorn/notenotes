import { Node, mergeAttributes } from "@tiptap/core";

// Видео — отдельный узел с настоящим <video controls>, а не просто
// markdown-ссылка на файл (жалоба: хочется смотреть видео прямо в
// заметке простым плеером, не только скачивать). Ссылкой на
// /api/uploads/..., не base64 — тот же принцип, что уже применён к
// картинкам (CLAUDE.md, см. ResizableImage). preload="metadata" даёт
// браузеру показать первый кадр как превью без отдельной генерации
// постера на бэкенде — на 768 МБ backend-контейнере лишний ffmpeg-шаг
// был бы неоправданно тяжёлым для этой пользы.
export const Video = Node.create({
  name: "video",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      src: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("src"),
        renderHTML: (attrs: { src?: string | null }) => (attrs.src ? { src: attrs.src } : {}),
      },
      filename: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-filename"),
        renderHTML: (attrs: { filename?: string | null }) => (attrs.filename ? { "data-filename": attrs.filename } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "video[src]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "video",
      mergeAttributes(HTMLAttributes, {
        controls: "",
        preload: "metadata",
        style: "max-width: 100%; max-height: 70vh; border-radius: 0.375rem;",
      }),
    ];
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void },
          node: { attrs: { src: string; filename?: string | null } },
        ) {
          const { src, filename } = node.attrs;
          const filenameAttr = filename ? ` data-filename="${filename.replace(/"/g, "&quot;")}"` : "";
          state.write(
            `<video src="${src.replace(/"/g, "&quot;")}" controls preload="metadata" style="max-width: 100%; max-height: 70vh;"${filenameAttr}></video>`,
          );
        },
        parse: {},
      },
    };
  },
});
