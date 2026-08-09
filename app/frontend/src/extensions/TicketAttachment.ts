import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import TicketAttachmentCard from "../components/TicketAttachmentCard";

// Карточка распознанного билета (жд/авиа/на мероприятие) — по образцу
// DocumentAttachment.ts (тот же приём: один самодостаточный тег на одной
// строке, структурированные поля в атрибутах, а не в дочернем markdown-
// содержимом — иначе многострочный распознанный текст обрывал бы
// html_block markdown-it на первой пустой строке). Ставится бэкендом
// (app/backend/app/tickets.py) при замене плейсхолдера — не вставляется
// вручную через тулбар редактора, в отличие от DocumentAttachment.
export interface TicketAttachmentData {
  url: string;
  filename: string;
  ticketType: string;
  datetimeStart: string;
  datetimeEnd: string;
  locationFrom: string;
  locationTo: string;
  seat: string;
  title: string;
  rawText: string;
  code: string;
}

export function serializeTicketAttachment(data: TicketAttachmentData): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/\n/g, "&#10;").replace(/"/g, "&quot;");
  const parts = [`data-url="${esc(data.url)}"`];
  if (data.filename) parts.push(`data-filename="${esc(data.filename)}"`);
  parts.push(`data-ticket-type="${esc(data.ticketType || "other")}"`);
  if (data.datetimeStart) parts.push(`data-datetime-start="${esc(data.datetimeStart)}"`);
  if (data.datetimeEnd) parts.push(`data-datetime-end="${esc(data.datetimeEnd)}"`);
  if (data.locationFrom) parts.push(`data-location-from="${esc(data.locationFrom)}"`);
  if (data.locationTo) parts.push(`data-location-to="${esc(data.locationTo)}"`);
  if (data.seat) parts.push(`data-seat="${esc(data.seat)}"`);
  if (data.title) parts.push(`data-title="${esc(data.title)}"`);
  if (data.code) parts.push(`data-code="${esc(data.code)}"`);
  // data-text, не data-raw-text — полнотекстовый поиск на бэкенде
  // (миграция 0015) индексирует только этот конкретный атрибут, тот же
  // приём, что у DocumentAttachment.
  if (data.rawText) parts.push(`data-text="${esc(data.rawText)}"`);
  return `<div data-ticket-attachment ${parts.join(" ")}></div>`;
}

export const TicketAttachment = Node.create({
  name: "ticketAttachment",
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
      ticketType: {
        default: "other",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-ticket-type") ?? "other",
        renderHTML: (attrs: { ticketType?: string }) => ({ "data-ticket-type": attrs.ticketType || "other" }),
      },
      datetimeStart: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-datetime-start") ?? "",
        renderHTML: (attrs: { datetimeStart?: string }) =>
          attrs.datetimeStart ? { "data-datetime-start": attrs.datetimeStart } : {},
      },
      datetimeEnd: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-datetime-end") ?? "",
        renderHTML: (attrs: { datetimeEnd?: string }) =>
          attrs.datetimeEnd ? { "data-datetime-end": attrs.datetimeEnd } : {},
      },
      locationFrom: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-location-from") ?? "",
        renderHTML: (attrs: { locationFrom?: string }) =>
          attrs.locationFrom ? { "data-location-from": attrs.locationFrom } : {},
      },
      locationTo: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-location-to") ?? "",
        renderHTML: (attrs: { locationTo?: string }) => (attrs.locationTo ? { "data-location-to": attrs.locationTo } : {}),
      },
      seat: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-seat") ?? "",
        renderHTML: (attrs: { seat?: string }) => (attrs.seat ? { "data-seat": attrs.seat } : {}),
      },
      title: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-title") ?? "",
        renderHTML: (attrs: { title?: string }) => (attrs.title ? { "data-title": attrs.title } : {}),
      },
      rawText: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-text") ?? "",
        renderHTML: (attrs: { rawText?: string }) => (attrs.rawText ? { "data-text": attrs.rawText } : {}),
      },
      code: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-code") ?? "",
        renderHTML: (attrs: { code?: string }) => (attrs.code ? { "data-code": attrs.code } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-ticket-attachment]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-ticket-attachment": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(TicketAttachmentCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: TicketAttachmentData },
        ) {
          state.write(serializeTicketAttachment(node.attrs));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
