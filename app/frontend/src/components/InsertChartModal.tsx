import { useState } from "react";
import { ChartColumn, ChartLine, ChartPie, ChartScatter, Search, Table as TableIcon } from "lucide-react";
import { useItems, useTable } from "../api/hooks";
import type { ChartEmbedAttrs } from "../extensions/ChartEmbed";
import { CHART_KINDS, type ChartKind } from "../lib/chartData";
import { t } from "../i18n";
import Spinner from "./Spinner";

// Два шага: выбрать таблицу спейса, затем вид графика и столбцы. Новая
// таблица здесь не создаётся — графику нужны данные, а их пока нет;
// для этого есть «/таблица» (InsertTableModal.tsx).
const KIND_ICONS: Record<ChartKind, typeof ChartLine> = { line: ChartLine, bar: ChartColumn, pie: ChartPie, scatter: ChartScatter };

export default function InsertChartModal({
  spaceId,
  onInsert,
  onCancel,
}: {
  spaceId: string;
  onInsert: (attrs: ChartEmbedAttrs) => void;
  onCancel: () => void;
}) {
  const [tableId, setTableId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const { data: items, isLoading } = useItems(spaceId, undefined, undefined);
  const tables = (items ?? []).filter((i) => i.material_type === "table" && i.title.toLowerCase().includes(query.trim().toLowerCase()));

  return (
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-3xl bg-surface p-4 shadow-xl">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-primary">
          <ChartLine size={16} className="text-subtle" />
          {t("chart.title")}
        </div>
        {tableId ? (
          <ChartSetup tableId={tableId} onBack={() => setTableId(null)} onInsert={onInsert} onCancel={onCancel} />
        ) : (
          <>
            <span className="mb-1 block text-xs text-subtle">{t("chart.pickTable")}</span>
            <label className="relative mb-2 block">
              <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-subtle" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("chart.searchTables")}
                className="w-full h-10 rounded-xl border bg-surface pl-8 pr-3 text-sm outline-none focus:ring-2 focus:ring-brand/40"
              />
            </label>
            <div className="mb-3 max-h-56 overflow-y-auto rounded border">
              {isLoading ? (
                <div className="flex items-center justify-center p-4 text-subtle">
                  <Spinner size={16} />
                </div>
              ) : tables.length === 0 ? (
                <div className="p-3 text-center text-xs text-subtle">{items && items.length > 0 && query ? t("chart.notFound") : t("chart.noTables")}</div>
              ) : (
                <ul>
                  {tables.map((table) => (
                    <li key={table.id}>
                      <button
                        onClick={() => setTableId(table.id)}
                        className="flex w-full items-center gap-2 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted-hover"
                      >
                        <TableIcon size={13} className="shrink-0 text-subtle" />
                        <span className="truncate">{table.title || t("chart.untitled")}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex justify-end">
              <button onClick={onCancel} className="h-10 rounded-xl px-4 text-sm font-bold text-secondary hover:bg-muted">
                {t("chart.cancel")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ChartSetup({
  tableId,
  onBack,
  onInsert,
  onCancel,
}: {
  tableId: string;
  onBack: () => void;
  onInsert: (attrs: ChartEmbedAttrs) => void;
  onCancel: () => void;
}) {
  const { data: table, isLoading } = useTable(tableId);
  const [kind, setKind] = useState<ChartKind>("line");
  const [x, setX] = useState<string>("");
  const [y, setY] = useState<string[]>([]);
  const [series, setSeries] = useState("");
  const [size, setSize] = useState("");
  const [title, setTitle] = useState("");
  const [initialized, setInitialized] = useState(false);

  if (isLoading || !table) {
    return (
      <div className="flex items-center justify-center p-6 text-subtle">
        <Spinner size={16} />
      </div>
    );
  }

  // Разумное начало: первый столбец — ось X, первый числовой — значения.
  if (!initialized) {
    setInitialized(true);
    const first = table.columns[0];
    const numeric = table.columns.find((c) => c.type === "number") ?? table.columns[1] ?? first;
    if (first) setX(first.id);
    if (numeric) setY([numeric.id]);
  }

  const single = kind === "pie" || kind === "scatter" || series !== "";
  const canInsert = y.length > 0 && (kind === "line" || kind === "bar" ? x !== "" : true) && (kind !== "pie" || x !== "");

  function toggleY(id: string) {
    setY((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : single ? [id] : [...prev, id]));
  }

  function insert() {
    if (!canInsert) return;
    onInsert({
      tableId,
      kind,
      x: x || null,
      y: single ? y.slice(0, 1) : y,
      series: kind === "pie" ? null : series || null,
      size: kind === "scatter" ? size || null : null,
      title: title.trim(),
    });
  }

  const select = "w-full h-9 rounded-xl border bg-surface px-2 text-sm outline-none focus:ring-2 focus:ring-brand/40";
  const columnOptions = (allowNone: boolean) => (
    <>
      {allowNone && <option value="">{t("chart.none")}</option>}
      {table.columns.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </>
  );

  return (
    <>
      <button onClick={onBack} className="mb-3 flex items-center gap-2 text-xs text-secondary hover:text-primary">
        <TableIcon size={13} className="text-subtle" />
        <span className="truncate">{table.title || t("chart.untitled")}</span>
        <span className="text-subtle">· {t("chart.back")}</span>
      </button>

      <div className="mb-3 grid grid-cols-4 gap-1 rounded border p-0.5 text-xs">
        {CHART_KINDS.map((k) => {
          const Icon = KIND_ICONS[k];
          return (
            <button
              key={k}
              type="button"
              aria-pressed={kind === k}
              onClick={() => {
                setKind(k);
                if (k === "pie" || k === "scatter") setY((prev) => prev.slice(0, 1));
              }}
              className={`flex items-center justify-center gap-1 rounded px-1 py-1.5 ${kind === k ? "bg-accent text-on-accent" : "text-secondary hover:bg-muted-hover"}`}
            >
              <Icon size={13} />
              {t(`chart.kind.${k}`)}
            </button>
          );
        })}
      </div>

      <label className="mb-2 block">
        <span className="mb-1 block text-xs text-subtle">{kind === "pie" ? t("chart.pieLabels") : t("chart.xAxis")}</span>
        <select value={x} onChange={(e) => setX(e.target.value)} className={select}>
          {kind === "scatter" && <option value="">{t("chart.rowIndex")}</option>}
          {columnOptions(false)}
        </select>
      </label>

      <fieldset className="mb-2">
        <legend className="mb-1 block text-xs text-subtle">{t("chart.yAxis")}</legend>
        <div className="flex flex-wrap gap-1">
          {table.columns.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={y.includes(c.id)}
              onClick={() => toggleY(c.id)}
              className={`rounded-full border px-2.5 py-1 text-xs ${y.includes(c.id) ? "border-brand bg-brand-soft text-brand-text" : "text-secondary hover:bg-muted-hover"}`}
            >
              {c.name}
            </button>
          ))}
        </div>
      </fieldset>

      {kind !== "pie" && (
        <label className="mb-2 block">
          <span className="mb-1 block text-xs text-subtle">{t("chart.series")}</span>
          <select
            value={series}
            onChange={(e) => {
              setSeries(e.target.value);
              if (e.target.value) setY((prev) => prev.slice(0, 1));
            }}
            className={select}
          >
            {columnOptions(true)}
          </select>
        </label>
      )}

      {kind === "scatter" && (
        <label className="mb-2 block">
          <span className="mb-1 block text-xs text-subtle">{t("chart.sizeColumn")}</span>
          <select value={size} onChange={(e) => setSize(e.target.value)} className={select}>
            {columnOptions(true)}
          </select>
        </label>
      )}

      <label className="mb-4 block">
        <span className="mb-1 block text-xs text-subtle">{t("chart.caption")}</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && insert()} className={select} />
      </label>

      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="h-10 rounded-xl px-4 text-sm font-bold text-secondary hover:bg-muted">
          {t("chart.cancel")}
        </button>
        <button onClick={insert} disabled={!canInsert} className="h-10 rounded-xl bg-accent px-4 text-sm font-bold text-on-accent disabled:opacity-40">
          {t("chart.insert")}
        </button>
      </div>
    </>
  );
}
