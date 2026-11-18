import { useMemo } from "react";
import type { TableDetail } from "../api/types";
import { t } from "../i18n";
import {
  buildPie,
  buildSeries,
  formatNumber,
  formatX,
  niceTicks,
  PALETTE,
  type ChartData,
  type ChartSpec,
  type Series,
} from "../lib/chartData";

// Отрисовка графика голым SVG — четыре простых вида не стоят библиотеки
// на сотни килобайт в бандле. viewBox фиксированный, ширина 100%: тот же
// график читается и на телефоне, и в широкой заметке.
const W = 640;
const H = 300;
const ML = 52;
const MR = 16;
const MT = 12;
const MB = 34;
const PLOT_W = W - ML - MR;
const PLOT_H = H - MT - MB;

function pad(min: number, max: number, ratio = 0.05): [number, number] {
  if (min === max) {
    const delta = min === 0 ? 1 : Math.abs(min) * ratio * 4;
    return [min - delta, max + delta];
  }
  const delta = (max - min) * ratio;
  return [min - delta, max + delta];
}

function xDomain(data: ChartData): [number, number] {
  if (data.xKind === "category") return [-0.5, Math.max(data.categories.length - 0.5, 0.5)];
  const xs = data.series.flatMap((s) => s.points.map((p) => p.x));
  return pad(Math.min(...xs), Math.max(...xs), 0.04);
}

function yDomain(data: ChartData, includeZero: boolean): [number, number] {
  const ys = data.series.flatMap((s) => s.points.map((p) => p.y));
  let min = Math.min(...ys);
  let max = Math.max(...ys);
  if (includeZero) {
    min = Math.min(0, min);
    max = Math.max(0, max);
  }
  const [lo, hi] = pad(min, max, 0.08);
  return includeZero ? [Math.min(lo, 0) === 0 ? 0 : lo, hi] : [lo, hi];
}

function xTicks(data: ChartData, [x0, x1]: [number, number]): number[] {
  if (data.xKind === "category") {
    const step = Math.ceil(data.categories.length / 8);
    return data.categories.map((_, i) => i).filter((i) => i % step === 0);
  }
  if (data.xKind === "number") return niceTicks(x0, x1, 6);
  const distinct = [...new Set(data.series.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b);
  if (distinct.length <= 7) return distinct;
  const step = (distinct.length - 1) / 6;
  return Array.from({ length: 7 }, (_, i) => distinct[Math.round(i * step)]);
}

function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary" data-testid="chart-legend">
      {series.map((s, i) => (
        <li key={s.name} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
          {s.name}
        </li>
      ))}
    </ul>
  );
}

function Cartesian({ table, spec }: { table: TableDetail; spec: ChartSpec }) {
  const data = useMemo(() => buildSeries(table, spec, { categorical: spec.kind === "bar" }), [table, spec]);
  const hasPoints = data.series.some((s) => s.points.length > 0);
  if (!hasPoints) return <p className="py-6 text-center text-sm text-subtle">{t("chart.noData")}</p>;

  const [x0, x1] = xDomain(data);
  const [y0, y1] = yDomain(data, spec.kind === "bar");
  const sx = (v: number) => ML + ((v - x0) / (x1 - x0)) * PLOT_W;
  const sy = (v: number) => MT + (1 - (v - y0) / (y1 - y0)) * PLOT_H;
  const yTicks = niceTicks(y0, y1, 5);
  const xs = xTicks(data, [x0, x1]);

  const sizes = data.series.flatMap((s) => s.points.map((p) => p.size ?? 0));
  const maxSize = Math.max(...sizes, 0);
  const radius = (size: number | null) => (size === null || maxSize <= 0 ? 4 : 3 + Math.sqrt(Math.max(size, 0) / maxSize) * 14);

  const groupWidth = (PLOT_W / Math.max(data.categories.length, 1)) * 0.7;
  const barWidth = groupWidth / Math.max(data.series.length, 1);

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img" aria-label={spec.title || t("chart.title")}>
        <g className="text-subtle" fill="currentColor" fontSize="11">
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={ML} x2={W - MR} y1={sy(v)} y2={sy(v)} stroke="currentColor" strokeOpacity="0.15" />
              <text x={ML - 6} y={sy(v) + 4} textAnchor="end">
                {formatNumber(v)}
              </text>
            </g>
          ))}
          {xs.map((v) => (
            <text key={v} x={sx(v)} y={H - MB + 16} textAnchor="middle">
              {formatX(v, data.xKind, data.categories)}
            </text>
          ))}
          <line x1={ML} x2={W - MR} y1={MT + PLOT_H} y2={MT + PLOT_H} stroke="currentColor" strokeOpacity="0.35" />
        </g>
        {data.series.map((s, si) => {
          const color = PALETTE[si % PALETTE.length];
          if (spec.kind === "bar") {
            const zero = sy(Math.max(y0, Math.min(0, y1)));
            return (
              <g key={s.name} fill={color} data-testid="chart-series">
                {s.points.map((p) => {
                  const left = sx(p.x) - groupWidth / 2 + si * barWidth;
                  const top = Math.min(sy(p.y), zero);
                  return (
                    <rect key={p.rowId + p.x} x={left} y={top} width={Math.max(barWidth - 1, 1)} height={Math.max(Math.abs(sy(p.y) - zero), 1)} rx="2">
                      <title>{`${s.name}: ${p.label} — ${formatNumber(p.y)}`}</title>
                    </rect>
                  );
                })}
              </g>
            );
          }
          const path = s.points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.x).toFixed(1)} ${sy(p.y).toFixed(1)}`).join(" ");
          return (
            <g key={s.name} data-testid="chart-series">
              {spec.kind === "line" && s.points.length > 1 && (
                <path d={path} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              )}
              {s.points.map((p) => (
                <circle
                  key={p.rowId + p.x}
                  cx={sx(p.x)}
                  cy={sy(p.y)}
                  r={spec.kind === "scatter" ? radius(p.size) : 3.5}
                  fill={color}
                  fillOpacity={spec.kind === "scatter" ? 0.65 : 1}
                  stroke={spec.kind === "scatter" ? color : "none"}
                >
                  <title>{`${s.name}: ${p.label} — ${formatNumber(p.y)}${p.size !== null ? ` (${formatNumber(p.size)})` : ""}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      <Legend series={data.series} />
    </>
  );
}

function Pie({ table, spec }: { table: TableDetail; spec: ChartSpec }) {
  const slices = useMemo(() => buildPie(table, spec), [table, spec]);
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  if (total <= 0) return <p className="py-6 text-center text-sm text-subtle">{t("chart.noData")}</p>;

  const R = 100;
  const cx = 120;
  const cy = 120;
  let angle = -Math.PI / 2;
  const paths = slices.map((s, i) => {
    const sweep = (s.value / total) * 2 * Math.PI;
    const start = angle;
    angle += sweep;
    const large = sweep > Math.PI ? 1 : 0;
    const x1 = cx + R * Math.cos(start);
    const y1 = cy + R * Math.sin(start);
    const x2 = cx + R * Math.cos(angle);
    const y2 = cy + R * Math.sin(angle);
    const d =
      slices.length === 1
        ? `M${cx - R} ${cy} A${R} ${R} 0 1 1 ${cx + R} ${cy} A${R} ${R} 0 1 1 ${cx - R} ${cy}`
        : `M${cx} ${cy} L${x1.toFixed(2)} ${y1.toFixed(2)} A${R} ${R} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
    return { ...s, d, color: PALETTE[i % PALETTE.length] };
  });

  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 240 240" className="block w-56 max-w-full" role="img" aria-label={spec.title || t("chart.title")}>
        {paths.map((p) => (
          <path key={p.label} d={p.d} fill={p.color} stroke="white" strokeWidth="1.5" data-testid="chart-slice">
            <title>{`${p.label} — ${formatNumber(p.value)} (${Math.round((p.value / total) * 100)}%)`}</title>
          </path>
        ))}
      </svg>
      <ul className="flex-1 space-y-1 text-xs text-secondary" data-testid="chart-legend">
        {paths.map((p) => (
          <li key={p.label} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: p.color }} />
            <span className="truncate">{p.label}</span>
            <span className="ml-auto tabular-nums text-subtle">{Math.round((p.value / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ChartSvg({ table, spec }: { table: TableDetail; spec: ChartSpec }) {
  return spec.kind === "pie" ? <Pie table={table} spec={spec} /> : <Cartesian table={table} spec={spec} />;
}
