import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import DocumentAttachmentCard from "../components/DocumentAttachmentCard";

// Карточка вложенного файла (PDF/документ, что угодно кроме картинок и
// видео — у тех уже свои узлы): иконка формата + имя файла вместо голой
// markdown-ссылки, и для PDF — спойлер с распознанным текстом вместо
// плоских абзацев прямо в заметке (жалоба: "и текст этот как-то аккуратно
// прикапывать для контекста"). Тот же приём round-trip, что у LinkPreview
// (см. её комментарий про markdown-it html_block) — но текст здесь в
// АТРИБУТЕ, не как дочерний markdown-контент: пустая строка внутри
// распознанного текста (у многостраничных PDF между страницами) обрывала
// бы html_block, если бы текст шёл обычным содержимым. Перевод настоящих
// переносов строк в &#10; держит весь тег на одной строке без потери
// текста — браузерный DOMParser декодирует сущность обратно в перенос
// сам при чтении атрибута.
// Экспортируется отдельно, чтобы raw-режим редактора (обычная текстовая
// вставка markdown-строки, без прохода через ProseMirror-схему) мог
// вставить тот же самый формат тега сам, не дублируя экранирование.
export function serializeDocumentAttachment(url: string, filename: string, text: string): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/\n/g, "&#10;").replace(/"/g, "&quot;");
  const parts = [`data-url="${esc(url)}"`];
  if (filename) parts.push(`data-filename="${esc(filename)}"`);
  if (text) parts.push(`data-text="${esc(text)}"`);
  return `<div data-doc-attachment ${parts.join(" ")}></div>`;
}

export const DocumentAttachment = Node.create({
  name: "documentAttachment",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      url: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-url"),
        renderHTML: (attrs: { url?: string | null }) => (attrs.url ? { "data-url": attrs.url } : {}),
      },
      filename: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-filename") ?? "",
        renderHTML: (attrs: { filename?: string }) => (attrs.filename ? { "data-filename": attrs.filename } : {}),
      },
      text: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-text") ?? "",
        renderHTML: (attrs: { text?: string }) => (attrs.text ? { "data-text": attrs.text } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-doc-attachment]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-doc-attachment": "" })];
  },

  addNodeView() {
    // Кастомный stopEvent тут не нужен: дефолтная реализация в @tiptap/core
    // уже отдаёт события с target.isContentEditable браузеру напрямую, не
    // трогая их сама — этого достаточно вместе с contentEditable={true} на
    // спойлере в DocumentAttachmentCard.tsx (см. комментарий там).
    return ReactNodeViewRenderer(DocumentAttachmentCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: { url: string; filename: string; text: string } },
        ) {
          const { url, filename, text } = node.attrs;
          state.write(serializeDocumentAttachment(url, filename, text));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
