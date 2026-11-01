import type { Routine } from "../api/types";
import { dateLocale, t } from "../i18n";
import { computeInsights, signedMinutes, type DayLevel, type Level, type SlotInsight } from "../lib/routineInsights";

// Попадание во время по журналу рутины (просьба владельца 01.11): круг-
// циферблат со стрелкой на времени плана и точками фактических приёмов
// вокруг неё (раньше — против часовой, позже — по), полоса обычного окна
// попадания, и клетки последних недель. Цвета: ±10 мин — зелёный, до часа —
// янтарный, больше часа или «не дали» — красный.

const LEVEL_COLOR: Record<Level, string> = {
  ok: "rgb(var(--color-lime))",
  warn: "rgb(var(--color-warning))",
  bad: "rgb(var(--color-danger))",
};

const DAY_CLASS: Record<DayLevel, string> = {
  none: "bg-muted",
  pending: "border-2 border-dashed border-strong bg-transparent",
  skipped: "bg-muted-active",
  ok: "bg-lime",
  warn: "bg-warning",
  bad: "bg-danger",
};

// Один оборот — 12 часов, как на обычных часах: 0,5° на минуту.
const DEG_PER_MINUTE = 360 / 720;
// Дальше ±2 часов точки прижимаются к краю шкалы, чтобы не уйти на другую
// сторону круга и не читаться как «раньше».
const CLAMP_MINUTES = 120;

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function arcPath(cx: number, cy: number, r: number, fromDeg: number, toDeg: number): string {
  const [x1, y1] = polar(cx, cy, r, fromDeg);
  const [x2, y2] = polar(cx, cy, r, toDeg);
  const large = toDeg - fromDeg > 180 ? 1 : 0;
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

function Dial({ slot }: { slot: SlotInsight }) {
  const size = 156;
  const c = size / 2;
  const r = 66;
  const base = (slot.plannedMinutes % 720) * DEG_PER_MINUTE;
  const clamp = (v: number) => Math.max(-CLAMP_MINUTES, Math.min(CLAMP_MINUTES, v));
  const [hx, hy] = polar(c, c, r * 0.72, base);
  const window = slot.window && slot.window[0] !== slot.window[1] ? slot.window.map(clamp) : null;

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${slot.slot}`}>
        <circle cx={c} cy={c} r={r} className="fill-surface stroke-default" strokeWidth={1.5} />
        {Array.from({ length: 12 }, (_, i) => {
          const [x1, y1] = polar(c, c, r - 2, i * 30);
          const [x2, y2] = polar(c, c, r - (i % 3 === 0 ? 8 : 5), i * 30);
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} className="stroke-strong" strokeWidth={i % 3 === 0 ? 2 : 1} />;
        })}
        {window && (
          <path
            d={arcPath(c, c, r * 0.88, base + window[0] * DEG_PER_MINUTE, base + window[1] * DEG_PER_MINUTE)}
            fill="none"
            stroke="rgb(var(--color-brand))"
            strokeOpacity={0.22}
            strokeWidth={11}
            strokeLinecap="round"
          />
        )}
        <line x1={c} y1={c} x2={hx} y2={hy} stroke="rgb(var(--color-brand))" strokeWidth={3} strokeLinecap="round" />
        <circle cx={c} cy={c} r={3.5} fill="rgb(var(--color-brand))" />
        {slot.offsets.map((offset, i) => {
          const [x, y] = polar(c, c, r * 0.88, base + clamp(offset) * DEG_PER_MINUTE);
          const level = Math.abs(offset) <= 10 ? "ok" : Math.abs(offset) <= 60 ? "warn" : "bad";
          return <circle key={i} cx={x} cy={y} r={4.5} fill={LEVEL_COLOR[level]} fillOpacity={0.9} className="stroke-surface" strokeWidth={1.5} />;
        })}
      </svg>
      <div className="mt-1 text-[15px] font-extrabold text-primary">{slot.slot}</div>
      <div className="text-[12px] font-semibold text-subtle">
        {slot.median !== null && t("routine.median", { n: signedMinutes(slot.median, dateLocale) })}
        {slot.median !== null && " · "}
        {t("routine.within10", { n: slot.within10, total: slot.offsets.length })}
      </div>
    </div>
  );
}

export default function RoutineInsights({ routine }: { routine: Routine }) {
  const insights = computeInsights(routine.doses, new Date(), 4, routine.timezone);
  if (insights.total === 0) return null;
  const showDials = routine.schedule.mode === "times" && insights.slots.length > 0 && insights.slots.length <= 3;
  const weekdays = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(2024, 0, 1 + i); // понедельник
    return d.toLocaleDateString(dateLocale, { weekday: "narrow" });
  });
  // Клетки раскладываются по неделям с понедельника: первая строка может
  // начинаться с пустых мест.
  const firstDow = (insights.days[0].date.getDay() + 6) % 7;

  return (
    <section aria-label={t("routine.insights")} className="mx-5 mt-5 lg:mx-6 lg:max-w-2xl">
      <h2 className="text-lg font-extrabold tracking-tight text-primary">{t("routine.insights")}</h2>
      <div className="mt-1 text-[13px] font-semibold text-subtle">
        {insights.median !== null ? `${t("routine.median", { n: signedMinutes(insights.median, dateLocale) })} · ` : ""}
        {t("routine.within10", { n: insights.within10, total: insights.offsets.length })}
        {insights.over60 + insights.missed > 0 ? ` · ${t("routine.offTrack", { n: insights.over60 + insights.missed })}` : ""}
      </div>

      {showDials && (
        <div className="mt-3 flex flex-wrap justify-around gap-3 rounded-[22px] bg-muted/60 px-3 py-4">
          {insights.slots.map((slot) => (
            <Dial key={slot.slot} slot={slot} />
          ))}
        </div>
      )}

      <div className="mt-3 rounded-[22px] bg-muted/60 px-4 py-3.5">
        <div className="text-[12px] font-extrabold uppercase tracking-wider text-subtle">{t("routine.last4weeks")}</div>
        <div className="mt-2 grid max-w-[340px] grid-cols-7 gap-1.5">
          {weekdays.map((w, i) => (
            <div key={i} className="text-center text-[11px] font-bold text-subtle">
              {w}
            </div>
          ))}
          {Array.from({ length: firstDow }, (_, i) => (
            <div key={`pad-${i}`} />
          ))}
          {insights.days.map((cell) => (
            <div
              key={cell.date.toISOString()}
              title={cell.date.toLocaleDateString(dateLocale, { day: "numeric", month: "short" })}
              className={`aspect-square rounded-md ${DAY_CLASS[cell.level]}`}
            />
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-semibold text-subtle">
          <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-lime" /> {t("routine.legendOk")}</span>
          <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-warning" /> {t("routine.legendWarn")}</span>
          <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-danger" /> {t("routine.legendBad")}</span>
          <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-muted-active" /> {t("routine.skipped")}</span>
        </div>
      </div>
    </section>
  );
}
