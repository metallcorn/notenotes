import type { Routine, RoutineDose } from "../api/types";

// Подписи для рутин (app/routines.py): сколько ждёт приём, какой день
// курса, опоздание. Чистые функции — чтобы тестировать без рендера.

export function humanMinutes(minutes: number, locale = "ru-RU"): string {
  const ru = locale.startsWith("ru");
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return ru ? `${m} мин` : `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (rest === 0) return ru ? `${h} ч` : `${h} h`;
  return ru ? `${h} ч ${String(rest).padStart(2, "0")} мин` : `${h} h ${String(rest).padStart(2, "0")} min`;
}

/** Сколько минут приём уже ждёт (0, если время ещё не наступило). */
export function waitingMinutes(dose: RoutineDose, now: Date = new Date()): number {
  const planned = new Date(dose.planned_at).getTime();
  return Math.max(0, Math.round((now.getTime() - planned) / 60_000));
}

/** На сколько минут опоздали с приёмом (0 — вовремя, в пределах 15 минут). */
export function lateMinutes(dose: RoutineDose): number {
  if (!dose.done_at) return 0;
  const diff = Math.round((new Date(dose.done_at).getTime() - new Date(dose.planned_at).getTime()) / 60_000);
  return diff > 15 ? diff : 0;
}

/** «День 3 из 14» для ограниченного курса, иначе null. */
export function dayOfCourse(routine: Pick<Routine, "starts_on" | "ends_on">, now: Date = new Date()): { day: number; total: number } | null {
  if (!routine.starts_on || !routine.ends_on) return null;
  const start = new Date(routine.starts_on + "T00:00:00");
  const end = new Date(routine.ends_on + "T00:00:00");
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const total = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
  if (total <= 0) return null;
  const day = Math.round((today.getTime() - start.getTime()) / 86_400_000) + 1;
  return { day: Math.min(Math.max(day, 1), total), total };
}

/** Кто передал приём другим, кроме самого читателя. */
export function deferredNames(dose: RoutineDose, meId: string | undefined): string[] {
  return dose.deferred_by.filter((d) => d.id !== meId).map((d) => d.name);
}

/** Приёмы одного местного дня (для карточки «Сегодня»). */
export function sameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
