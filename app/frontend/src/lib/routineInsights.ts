import type { Routine, RoutineDose } from "../api/types";

// Статистика попадания во время по журналу рутины (RoutineInsights.tsx):
// отклонение каждого приёма от плана, медиана, доля в «идеальном» окне,
// обычное окно (10–90-й процентиль), клетки последних недель. Чистые
// функции — проверяются тестом без рендера.
//
// Пороги — слова владельца (01.11): «±10 минут ничего не влияет, это почти
// идеальное попадание; час — уже не очень, может наложиться на другое».

export const ON_TIME_MINUTES = 10;
export const ACCEPTABLE_MINUTES = 60;

export type Level = "ok" | "warn" | "bad";

export function offsetMinutes(dose: Pick<RoutineDose, "status" | "done_at" | "planned_at">): number | null {
  if (dose.status !== "done" || !dose.done_at) return null;
  return Math.round((new Date(dose.done_at).getTime() - new Date(dose.planned_at).getTime()) / 60_000);
}

export function levelOf(offset: number): Level {
  const abs = Math.abs(offset);
  if (abs <= ON_TIME_MINUTES) return "ok";
  if (abs <= ACCEPTABLE_MINUTES) return "warn";
  return "bad";
}

/** «+40 мин» / «−12 мин» / «вовремя» — подпись к отклонению. */
export function offsetLabel(offset: number, locale = "ru-RU"): string {
  const ru = locale.startsWith("ru");
  if (Math.abs(offset) <= ON_TIME_MINUTES) return ru ? "вовремя" : "on time";
  const sign = offset > 0 ? "+" : "−";
  const abs = Math.abs(offset);
  if (abs < 60) return `${sign}${abs} ${ru ? "мин" : "min"}`;
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return `${sign}${h}${ru ? " ч" : " h"}${m ? ` ${String(m).padStart(2, "0")}` : ""}`;
}

/** «+1 мин» / «0 мин» / «−5 мин» / «+1 ч 35» — всегда со знаком, для медианы. */
export function signedMinutes(offset: number, locale = "ru-RU"): string {
  const ru = locale.startsWith("ru");
  if (offset === 0) return ru ? "0 мин" : "0 min";
  const sign = offset > 0 ? "+" : "−";
  const abs = Math.abs(offset);
  if (abs < 60) return `${sign}${abs} ${ru ? "мин" : "min"}`;
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return `${sign}${h}${ru ? " ч" : " h"}${m ? ` ${String(m).padStart(2, "0")}` : ""}`;
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
}

export function percentile(values: number[], p: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * p)));
  return sorted[idx];
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Слот расписания по времени плана в поясе рутины: «16:30». Пояс рутины,
 *  а не браузера: иначе после перевода часов один слот распадается на два,
 *  а у человека в другом поясе стрелка стоит не на том часе. */
export function slotKey(plannedAt: string, tz?: string): string {
  const d = new Date(plannedAt);
  if (!tz) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  try {
    const parts = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: tz }).formatToParts(d);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
    return `${get("hour")}:${get("minute")}`;
  } catch {
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
}

export interface SlotInsight {
  slot: string;
  /** Минут с полуночи — угол стрелки на циферблате. */
  plannedMinutes: number;
  offsets: number[];
  median: number | null;
  within10: number;
  /** Обычное окно попадания, 10-й и 90-й процентили отклонений. */
  window: [number, number] | null;
}

export type DayLevel = Level | "skipped" | "none" | "pending";

export interface DayCell {
  date: Date;
  level: DayLevel;
}

export interface Insights {
  total: number;
  done: number;
  skipped: number;
  missed: number;
  offsets: number[];
  median: number | null;
  within10: number;
  within60: number;
  over60: number;
  slots: SlotInsight[];
  days: DayCell[];
}

function localDayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const DAY_RANK: Record<DayLevel, number> = { none: 0, pending: 1, skipped: 2, ok: 3, warn: 4, bad: 5 };

export function computeInsights(doses: RoutineDose[], now: Date = new Date(), weeks = 4, tz?: string): Insights {
  const closed = doses.filter((d) => d.status !== "pending");
  const offsets: number[] = [];
  const bySlot = new Map<string, number[]>();
  const byDay = new Map<string, DayLevel>();

  const bump = (key: string, level: DayLevel) => {
    const current = byDay.get(key) ?? "none";
    if (DAY_RANK[level] > DAY_RANK[current]) byDay.set(key, level);
  };

  for (const dose of doses) {
    const dayKey = localDayKey(new Date(dose.planned_at));
    if (dose.status === "pending") {
      bump(dayKey, "pending");
      continue;
    }
    if (dose.status === "skipped") {
      bump(dayKey, "skipped");
      continue;
    }
    if (dose.status === "missed") {
      bump(dayKey, "bad");
      continue;
    }
    const offset = offsetMinutes(dose);
    if (offset === null) continue;
    offsets.push(offset);
    const slot = slotKey(dose.planned_at, tz);
    bySlot.set(slot, [...(bySlot.get(slot) ?? []), offset]);
    bump(dayKey, levelOf(offset));
  }

  const slots: SlotInsight[] = [...bySlot.entries()]
    .map(([slot, values]) => {
      const [h, m] = slot.split(":").map(Number);
      const lo = percentile(values, 0.1);
      const hi = percentile(values, 0.9);
      return {
        slot,
        plannedMinutes: h * 60 + m,
        offsets: values,
        median: median(values),
        within10: values.filter((v) => Math.abs(v) <= ON_TIME_MINUTES).length,
        window: lo !== null && hi !== null ? ([lo, hi] as [number, number]) : null,
      };
    })
    .sort((a, b) => a.plannedMinutes - b.plannedMinutes);

  const days: DayCell[] = [];
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  for (let i = weeks * 7 - 1; i >= 0; i -= 1) {
    const date = new Date(today);
    date.setDate(today.getDate() - i);
    days.push({ date, level: byDay.get(localDayKey(date)) ?? "none" });
  }

  return {
    total: closed.length,
    done: closed.filter((d) => d.status === "done").length,
    skipped: closed.filter((d) => d.status === "skipped").length,
    missed: closed.filter((d) => d.status === "missed").length,
    offsets,
    median: median(offsets),
    within10: offsets.filter((v) => Math.abs(v) <= ON_TIME_MINUTES).length,
    within60: offsets.filter((v) => Math.abs(v) > ON_TIME_MINUTES && Math.abs(v) <= ACCEPTABLE_MINUTES).length,
    over60: offsets.filter((v) => Math.abs(v) > ACCEPTABLE_MINUTES).length,
    slots,
    days,
  };
}

/** Журнал текстом — скопировать и отдать, например, ассистенту: по строке
 *  на приём, хронологически, с отклонением в минутах. */
export function journalText(routine: Pick<Routine, "title" | "subject" | "dose" | "schedule_text" | "doses">, locale = "ru-RU"): string {
  const ru = locale.startsWith("ru");
  const header = [routine.title, routine.subject, routine.dose, routine.schedule_text].filter(Boolean).join(" · ");
  const time = (iso: string) => {
    const d = new Date(iso);
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const lines = routine.doses
    .filter((d) => d.status !== "pending")
    .map((d) => {
      const planned = new Date(d.planned_at);
      const when = `${localDayKey(planned)} ${time(d.planned_at)}`;
      if (d.status === "done" && d.done_at) {
        const offset = offsetMinutes(d) ?? 0;
        const sign = offset >= 0 ? "+" : "−";
        return `${when} → ${time(d.done_at)} (${sign}${Math.abs(offset)} ${ru ? "мин" : "min"})${d.done_by_name ? ` · ${d.done_by_name}` : ""}`;
      }
      if (d.status === "skipped") return `${when} → ${ru ? "не нужно сегодня" : "not needed"}`;
      if (d.reported_by_name) return `${when} → ${ru ? "не дали" : "not given"} · ${d.reported_by_name}`;
      return `${when} → ${ru ? "никто не отметил" : "nobody confirmed"}`;
    });
  return [header, ...lines].join("\n");
}
