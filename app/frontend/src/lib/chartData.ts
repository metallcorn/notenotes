import type { TableDetail } from "../api/types";
import { dateLocale } from "../i18n";

// Данные графика из таблицы — чистые функции без React и без SVG, чтобы
// разбор дат «01.03.2026», чисел «72,5 кг» и группировку по сериям можно
// было проверить тестом по отдельности от отрисовки (ChartSvg.tsx).
//
// Столбцы в спецификации — по id (см. tools/charts.py): переименование
// столбца график не ломает, удаление — честно оставляет его пустым.

export type ChartKind = "line" | "bar" | "pie" | "scatter";
export const CHART_KINDS: ChartKind[] = ["line", "bar", "pie", "scatter"];

export interface ChartSpec {
  tableId: string;
  kind: ChartKind;
  x: string | null;
  y: string[];
  series: string | null;
  size: string | null;
  title: string;
}

export type XKind = "date" | "number" | "category";

export interface Point {
  x: number;
  label: string;
  y: number;
  size: number | null;
  rowId: string;
}

export interface Series {
  name: string;
  points: Point[];
}

export interface ChartData {
  xKind: XKind;
  categories: string[];
  series: Series[];
}

export interface PieSlice {
  label: string;
  value: number;
}

export const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

export function isChartKind(value: unknown): value is ChartKind {
  return typeof value === "string" && (CHART_KINDS as string[]).includes(value);
}

// Первое число в ячейке: «72,5 кг» → 72.5, «< 0,5» → 0.5, «—» → null.
// Запятая как десятичный разделитель — норма для польских и русских
// документов, из которых показания и переписываются.
export function parseNumber(raw: string | undefined | null): number | null {
  if (!raw) return null;
  const m = raw.replace(/\s/g, "").match(/-?\d+(?:[.,]\d+)?/);
  if (!m) return null;
  const n = Number(m[0].replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

const ISO_RE = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?/;
const DMY_RE = /^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:[ ,]+(\d{1,2}):(\d{2}))?\s*$/;

export function parseDate(raw: string | undefined | null): number | null {
  if (!raw) return null;
  const text = raw.trim();
  let y: number, mo: number, d: number, hh = 0, mm = 0;
  const iso = text.match(ISO_RE);
  const dmy = iso ? null : text.match(DMY_RE);
  if (iso) {
    [y, mo, d] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
    if (iso[4]) [hh, mm] = [Number(iso[4]), Number(iso[5])];
  } else if (dmy) {
    [d, mo, y] = [Number(dmy[1]), Number(dmy[2]), Number(dmy[3])];
    if (y < 100) y += 2000;
    if (dmy[4]) [hh, mm] = [Number(dmy[4]), Number(dmy[5])];
  } else {
    return null;
  }
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const date = new Date(y, mo - 1, d, hh, mm);
  return date.getMonth() === mo - 1 && date.getDate() === d ? date.getTime() : null;
}

// Ось X — дата, число или категории: решается по большинству заполненных
// ячеек, чтобы одна опечатка не превращала даты в подписи.
export function detectXKind(values: string[]): XKind {
  const filled = values.filter((v) => v.trim() !== "");
  if (filled.length === 0) return "category";
  const threshold = filled.length * 0.8;
  if (filled.filter((v) => parseDate(v) !== null).length >= threshold) return "date";
  if (filled.filter((v) => parseNumber(v) !== null).length >= threshold) return "number";
  return "category";
}

function columnName(table: TableDetail, id: string | null): string {
  return table.columns.find((c) => c.id === id)?.name ?? "";
}

export function buildSeries(table: TableDetail, spec: ChartSpec, options: { categorical?: boolean } = {}): ChartData {
  const xValues = table.rows.map((row, index) => (spec.x ? (row.cells[spec.x] ?? "") : String(index + 1)));
  const xKind: XKind = options.categorical ? "category" : spec.x ? detectXKind(xValues) : "number";

  const categories: string[] = [];
  const categoryIndex = new Map<string, number>();
  const bySeries = new Map<string, Series>();

  table.rows.forEach((row, index) => {
    const xRaw = xValues[index];
    let x: number | null;
    if (xKind === "date") x = parseDate(xRaw);
    else if (xKind === "number") x = parseNumber(xRaw);
    else {
      const label = xRaw.trim() || "—";
      if (!categoryIndex.has(label)) {
        categoryIndex.set(label, categories.length);
        categories.push(label);
      }
      x = categoryIndex.get(label)!;
    }
    if (x === null) return;

    const seriesValue = spec.series ? (row.cells[spec.series] ?? "").trim() || "—" : null;
    const size = spec.size ? parseNumber(row.cells[spec.size]) : null;
    for (const yId of spec.y) {
      const y = parseNumber(row.cells[yId]);
      if (y === null) continue;
      const name =
        seriesValue === null ? columnName(table, yId) : spec.y.length > 1 ? `${seriesValue} · ${columnName(table, yId)}` : seriesValue;
      let series = bySeries.get(name);
      if (!series) {
        series = { name, points: [] };
        bySeries.set(name, series);
      }
      series.points.push({ x, label: xKind === "category" ? categories[x] : xRaw.trim(), y, size, rowId: row.id });
    }
  });

  const series = [...bySeries.values()];
  if (xKind !== "category") for (const s of series) s.points.sort((a, b) => a.x - b.x);
  return { xKind, categories, series };
}

// Круг: доли по подписям из столбца X, одинаковые подписи складываются
// («Гемоглобин» дважды — одна доля). Нули и отрицательные долей не дают.
export function buildPie(table: TableDetail, spec: ChartSpec): PieSlice[] {
  const yId = spec.y[0];
  if (!yId) return [];
  const totals = new Map<string, number>();
  for (const row of table.rows) {
    const value = parseNumber(row.cells[yId]);
    if (value === null || value <= 0) continue;
    const label = (spec.x ? (row.cells[spec.x] ?? "") : "").trim() || "—";
    totals.set(label, (totals.get(label) ?? 0) + value);
  }
  return [...totals.entries()].map(([label, value]) => ({ label, value }));
}

// «Красивые» деления оси: шаг 1/2/2.5/5 × 10ⁿ, чтобы подписи были
// 0, 50, 100, а не 0, 47.3, 94.6.
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const rough = (max - min) / count;
  const power = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / power;
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
  const step = factor * power;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + 1e-9; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

export function formatNumber(value: number): string {
  return value.toLocaleString(dateLocale, { maximumFractionDigits: 2 });
}

export function formatX(value: number, xKind: XKind, categories: string[]): string {
  if (xKind === "category") return categories[value] ?? "";
  if (xKind === "date") return new Date(value).toLocaleDateString(dateLocale, { day: "2-digit", month: "2-digit", year: "2-digit" });
  return formatNumber(value);
}
