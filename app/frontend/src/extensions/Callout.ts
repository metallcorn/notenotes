import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import type { MarkdownSerializerState } from "prosemirror-markdown";
import type { Node as PmNode } from "@tiptap/pm/model";
import CalloutCard from "../components/CalloutCard";

// Реальный запрос: "спойлер" (сворачиваемый блок, чтобы данные под ним не
// мешались) и цветные плашки hint/info/warning/danger, как в Confluence/
// Slack. Один узел на все пять вариантов — общая структура (заголовок +
// произвольный блочный контент внутри), различается только оформлением и
// (только у спойлера) сворачиваемостью.
//
// В Markdown — HTML-блок с пустыми строками вокруг вложенного контента
// (тот же приём, что GFM-плагины для <details>): markdown-it отдаёт
// открывающий и закрывающий тег как отдельные html_block-токены, а между
// ними (после пустой строки) — обычные markdown-токены. Итоговая HTML-
// строка получается корректно вложенной, и ProseMirror DOMParser
// восстанавливает структуру через parseHTML ниже — их даже не нужно
// парсить каким-то особым способом.
export const CALLOUT_VARIANTS = ["spoiler", "hint", "info", "warning", "danger"] as const;
export type CalloutVariant = (typeof CALLOUT_VARIANTS)[number];

export const Callout = Node.create({
  name: "callout",
  group: "block",
  content: "block+",
  defining: true,

  addAttributes() {
    return {
      variant: {
        default: "info" as CalloutVariant,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-callout") || "info",
        renderHTML: (attrs: { variant: CalloutVariant }) => ({ "data-callout": attrs.variant }),
      },
      // Заголовок — только у спойлера (произвольный текст, который
      // пользователь задаёт); у остальных вариантов подпись фиксированная
      // (по variant), редактировать нечего.
      title: {
        default: null as string | null,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-title"),
        renderHTML: (attrs: { title: string | null }) => (attrs.title ? { "data-title": attrs.title } : {}),
      },
      open: {
        default: true,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-open") !== "0",
        renderHTML: (attrs: { open: boolean }) => (attrs.open ? {} : { "data-open": "0" }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-callout]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes), 0];
  },

  addNodeView() {
    return ReactNodeViewRenderer(CalloutCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: MarkdownSerializerState, node: PmNode) {
          // Тот же приём, что prosemirror-markdown использует для
          // blockquote (wrapBlock): closeBlock между открывающим тегом и
          // содержимым, и снова между содержимым и закрывающим — flushClose
          // сам вставляет пустую строку на каждой границе, вручную считать
          // переносы не нужно. Пустая строка вокруг вложенного markdown
          // обязательна — то, как GFM (markdown-it) распознаёт, что внутри
          // HTML-блока снова идёт обычный markdown, а не сырой HTML.
          const attrs = [`data-callout="${node.attrs.variant}"`];
          if (node.attrs.title) attrs.push(`data-title="${String(node.attrs.title).replace(/"/g, "&quot;")}"`);
          if (node.attrs.open === false) attrs.push('data-open="0"');
          state.write(`<div ${attrs.join(" ")}>`);
          state.closeBlock(node);
          state.renderContent(node);
          state.write("</div>");
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
