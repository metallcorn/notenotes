import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import VideoView from "../components/VideoView";

// Видео — отдельный узел с настоящим <video controls>, а не просто
// markdown-ссылка на файл (жалоба: хочется смотреть видео прямо в
// заметке простым плеером, не только скачивать). Ссылкой на
// /api/uploads/..., не base64 — тот же принцип, что уже применён к
// картинкам (CLAUDE.md, см. ResizableImage). preload="metadata" даёт
// браузеру показать первый кадр как превью без отдельной генерации
// постера на бэкенде — на 768 МБ backend-контейнере лишний ffmpeg-шаг
// был бы неоправданно тяжёлым для этой пользы.
//
// Реальная просьба: ширина отображения регулируется, как у картинки
// (ResizableImage.ts) — те же %-based width, VideoToolbar.tsx повторяет
// WIDTHS из ImageToolbar.tsx. NodeView (не голый renderHTML) нужен для
// оверлея с весом файла поверх постера — статичный HTML этого не умеет.
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
      width: {
        default: null,
        parseHTML: (element: HTMLElement) => element.style.width || null,
        renderHTML: (attrs: { width?: string | null }) => (attrs.width ? { style: `width: ${attrs.width}` } : {}),
      },
      // Байты — известны в момент загрузки (UploadResult.size_bytes),
      // сохраняются в самом узле, чтобы оверлей с весом не зависел от
      // повторного похода на бэкенд каждый раз, когда открывается заметка.
      size: {
        default: null,
        parseHTML: (element: HTMLElement) => {
          const raw = element.getAttribute("data-size");
          return raw ? Number(raw) : null;
        },
        renderHTML: (attrs: { size?: number | null }) => (attrs.size ? { "data-size": String(attrs.size) } : {}),
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

  addNodeView() {
    return ReactNodeViewRenderer(VideoView);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void },
          node: { attrs: { src: string; filename?: string | null; width?: string | null; size?: number | null } },
        ) {
          const { src, filename, width, size } = node.attrs;
          const filenameAttr = filename ? ` data-filename="${filename.replace(/"/g, "&quot;")}"` : "";
          const sizeAttr = size ? ` data-size="${size}"` : "";
          const style = `max-width: 100%; max-height: 70vh;${width ? ` width: ${width};` : ""}`;
          state.write(
            `<video src="${src.replace(/"/g, "&quot;")}" controls preload="metadata" style="${style}"${filenameAttr}${sizeAttr}></video>`,
          );
        },
        parse: {},
      },
    };
  },
});
