import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { useSearchParams } from "react-router-dom";
import { ChartColumn, ChartLine, ChartPie, ChartScatter, ExternalLink, Unlink } from "lucide-react";
import { useTable } from "../api/hooks";
import { useTableSync } from "../lib/useTableSync";
import { CHART_KINDS, isChartKind, type ChartKind, type ChartSpec } from "../lib/chartData";
import type { ChartEmbedAttrs } from "../extensions/ChartEmbed";
import { t } from "../i18n";
import ChartSvg from "./ChartSvg";
import Spinner from "./Spinner";

// Карточка графика по таблице — живой график прямо в тексте заметки.
// Узел хранит только ссылку (ChartEmbed.ts): удаление карточки таблицу
// не трогает, а удалённая таблица не роняет заметку (ветка isError).
// Подписка на WS таблицы — чтобы строка, добавленная ассистентом или
// другим участником, сразу появилась на графике.
const KIND_ICONS: Record<ChartKind, typeof ChartLine> = {
  line: ChartLine,
  bar: ChartColumn,
  pie: ChartPie,
  scatter: ChartScatter,
};

export default function ChartEmbedCard({ node, editor, getPos, updateAttributes }: NodeViewProps) {
  const attrs = node.attrs as ChartEmbedAttrs;
  const tableId = attrs.tableId ?? undefined;
  const { data: table, isLoading, isError } = useTable(tableId);
  useTableSync(tableId);
  const [, setSearchParams] = useSearchParams();
  const kind: ChartKind = isChartKind(attrs.kind) ? attrs.kind : "line";
  const Icon = KIND_ICONS[kind];

  function unlink() {
    const pos = typeof getPos === "function" ? getPos() : null;
    if (pos === null || pos === undefined) return;
    editor.chain().focus().deleteRange({ from: pos, to: pos + node.nodeSize }).run();
  }

  if (isError || !tableId) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <div className="flex max-w-md items-center gap-2 rounded border border-dashed bg-muted px-3 py-2 text-sm text-subtle">
          <span className="flex-1">{t("chart.unavailable")}</span>
          <button onClick={unlink} title={t("chart.unlink")} className="flex h-7 w-7 items-center justify-center hover:text-danger">
            <Unlink size={14} />
          </button>
        </div>
      </NodeViewWrapper>
    );
  }

  if (isLoading || !table) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <div className="flex max-w-md items-center justify-center rounded border bg-muted px-3 py-4">
          <Spinner size={16} />
        </div>
      </NodeViewWrapper>
    );
  }

  const spec: ChartSpec = { tableId: table.id, kind, x: attrs.x, y: attrs.y ?? [], series: attrs.series, size: attrs.size, title: attrs.title ?? "" };

  return (
    <NodeViewWrapper as="div" className="my-1">
      <div data-testid="chart-embed-card" className="overflow-hidden rounded border bg-surface">
        <div data-drag-handle draggable className="flex items-center gap-2 border-b bg-muted px-3 py-2">
          <Icon size={15} className="shrink-0 text-subtle" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-primary">{spec.title || table.title || t("chart.title")}</span>
          {kind !== "pie" && (
            <select
              value={kind}
              onChange={(e) => updateAttributes({ kind: e.target.value })}
              aria-label={t("chart.title")}
              className="h-7 rounded border bg-surface px-1 text-xs text-secondary outline-none"
            >
              {CHART_KINDS.filter((k) => k !== "pie").map((k) => (
                <option key={k} value={k}>
                  {t(`chart.kind.${k}`)}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={() => setSearchParams({ item: table.id })}
            title={t("chart.openTable")}
            className="flex h-7 w-7 shrink-0 items-center justify-center text-subtle hover:text-secondary"
          >
            <ExternalLink size={14} />
          </button>
          <button onClick={unlink} title={t("chart.unlink")} className="flex h-7 w-7 shrink-0 items-center justify-center text-subtle hover:text-danger">
            <Unlink size={14} />
          </button>
        </div>
        <div className="p-3">
          <ChartSvg table={table} spec={spec} />
        </div>
      </div>
    </NodeViewWrapper>
  );
}
