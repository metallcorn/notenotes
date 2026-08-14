import { Node, mergeAttributes } from "@tiptap/core";

// Аудио — отдельный узел с настоящим <audio controls>, тот же принцип, что
// Video.ts (реальная жалоба на превью файлов вообще: голосовая заметка/
// mp3, прикреплённые как файл, должны сразу проигрываться, не только
// скачиваться). Плеер сам по себе и есть превью — расшифровка (transcription.py)
// сейчас гоняется только для видео, для отдельно загруженных аудиофайлов
// не подключена намеренно: это отдельная фича, не часть жалобы про превью.
export const Audio = Node.create({
  name: "audio",
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
    return [{ tag: "audio[src]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "audio",
      mergeAttributes(HTMLAttributes, {
        controls: "",
        preload: "metadata",
        style: "max-width: 100%;",
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
            `<audio src="${src.replace(/"/g, "&quot;")}" controls preload="metadata" style="max-width: 100%;"${filenameAttr}></audio>`,
          );
        },
        parse: {},
      },
    };
  },
});
