import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import UrlCheckCard from "../components/UrlCheckCard";

// Виджет «Проверить по ссылке» — GET по сохранённому URL, показывает
// выбранные поля из ответа + кнопку «Обновить». Вставляется только
// ассистентом (tools/url_check.py::insert_url_check_block, тот же
// сериализатор на бэкенде, serialize_url_check) — пользователь не
// настраивает поля вручную, поэтому нет слэш-команды. Экспортируется, как
// и serializeDocumentAttachment, на случай если raw-режим редактора
// когда-нибудь тоже начнёт вставлять этот тег сам.
export function serializeUrlCheck(
  url: string,
  fields: { path: string; label: string }[],
  lastResult: string | null,
  lastFetchedAt: string | null,
  lastStatus: number | null,
): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/\n/g, "&#10;").replace(/"/g, "&quot;");
  const parts = [`data-url="${esc(url)}"`, `data-fields="${esc(JSON.stringify(fields))}"`];
  if (lastResult !== null) parts.push(`data-last-result="${esc(lastResult)}"`);
  if (lastFetchedAt) parts.push(`data-last-fetched-at="${esc(lastFetchedAt)}"`);
  if (lastStatus !== null) parts.push(`data-last-status="${lastStatus}"`);
  return `<div data-url-check ${parts.join(" ")}></div>`;
}

export const UrlCheckAttachment = Node.create({
  name: "urlCheck",
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
      // JSON-строка [{path, label}] — разбирается компонентом, не здесь:
      // атрибуту всё равно, что внутри, лишний парсинг на уровне схемы
      // только добавил бы ещё одно место, где он может не совпасть с тем,
      // что делает карточка.
      fields: {
        default: "[]",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-fields") ?? "[]",
        renderHTML: (attrs: { fields?: string }) => (attrs.fields ? { "data-fields": attrs.fields } : {}),
      },
      lastResult: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-last-result"),
        renderHTML: (attrs: { lastResult?: string | null }) =>
          attrs.lastResult !== null && attrs.lastResult !== undefined ? { "data-last-result": attrs.lastResult } : {},
      },
      lastFetchedAt: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-last-fetched-at"),
        renderHTML: (attrs: { lastFetchedAt?: string | null }) =>
          attrs.lastFetchedAt ? { "data-last-fetched-at": attrs.lastFetchedAt } : {},
      },
      lastStatus: {
        default: null,
        parseHTML: (element: HTMLElement) => {
          const v = element.getAttribute("data-last-status");
          return v ? Number(v) : null;
        },
        renderHTML: (attrs: { lastStatus?: number | null }) =>
          attrs.lastStatus !== null && attrs.lastStatus !== undefined ? { "data-last-status": String(attrs.lastStatus) } : {},
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-url-check]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-url-check": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(UrlCheckCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: {
            attrs: {
              url: string;
              fields: string;
              lastResult: string | null;
              lastFetchedAt: string | null;
              lastStatus: number | null;
            };
          },
        ) {
          const { url, fields, lastResult, lastFetchedAt, lastStatus } = node.attrs;
          state.write(serializeUrlCheck(url, JSON.parse(fields || "[]"), lastResult, lastFetchedAt, lastStatus));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
