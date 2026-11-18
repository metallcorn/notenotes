import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import ChartEmbedCard from "../components/ChartEmbedCard";
import { isChartKind, type ChartKind } from "../lib/chartData";

// График по таблице (material_type="table") прямо в тексте заметки. Как у
// TableEmbed.ts, узел хранит только ссылку: id таблицы, вид и id столбцов —
// значения живут в таблице и подтягиваются картой (ChartEmbedCard.tsx).
// Тот же самодостаточный тег, что пишет бэкенд (tools/charts.py
// serialize_chart) — обе стороны обязаны читать и писать его одинаково.
export interface ChartEmbedAttrs {
  tableId: string | null;
  kind: ChartKind;
  x: string | null;
  y: string[];
  series: string | null;
  size: string | null;
  title: string;
}

function escapeAttr(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function serializeChart(attrs: ChartEmbedAttrs): string {
  const parts = [`data-table-id="${attrs.tableId ?? ""}"`, `data-kind="${attrs.kind}"`];
  if (attrs.x) parts.push(`data-x="${attrs.x}"`);
  parts.push(`data-y="${attrs.y.join(",")}"`);
  if (attrs.series) parts.push(`data-series="${attrs.series}"`);
  if (attrs.size) parts.push(`data-size="${attrs.size}"`);
  if (attrs.title) parts.push(`data-title="${escapeAttr(attrs.title)}"`);
  return `<div data-chart ${parts.join(" ")}></div>`;
}

const optional = (name: string) => ({
  default: null,
  parseHTML: (element: HTMLElement) => element.getAttribute(name) || null,
  renderHTML: (attrs: Record<string, unknown>) => {
    const key = name.replace("data-", "");
    const value = attrs[key === "table-id" ? "tableId" : key];
    return value ? { [name]: String(value) } : {};
  },
});

export const ChartEmbed = Node.create({
  name: "chartEmbed",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      tableId: optional("data-table-id"),
      kind: {
        default: "line",
        parseHTML: (element: HTMLElement) => {
          const raw = element.getAttribute("data-kind");
          return isChartKind(raw) ? raw : "line";
        },
        renderHTML: (attrs: { kind?: string }) => ({ "data-kind": attrs.kind ?? "line" }),
      },
      x: optional("data-x"),
      y: {
        default: [],
        parseHTML: (element: HTMLElement) => (element.getAttribute("data-y") ?? "").split(",").filter(Boolean),
        renderHTML: (attrs: { y?: string[] }) => ({ "data-y": (attrs.y ?? []).join(",") }),
      },
      series: optional("data-series"),
      size: optional("data-size"),
      title: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-title") ?? "",
        renderHTML: (attrs: { title?: string }) => (attrs.title ? { "data-title": attrs.title } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-chart]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-chart": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ChartEmbedCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: ChartEmbedAttrs },
        ) {
          state.write(serializeChart(node.attrs));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
