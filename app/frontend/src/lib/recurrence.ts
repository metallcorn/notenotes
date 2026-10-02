// Человеческие названия периодов повтора. Машинные значения — те же, что
// на бэкенде (app/recurrence.py): фронтенд их не придумывает, только
// показывает, а валидирует сервер.
export const REPEAT_RULES = ["daily", "weekly", "monthly", "yearly"] as const;

export type RepeatRule = (typeof REPEAT_RULES)[number];

export const REPEAT_LABELS: Record<RepeatRule, string> = {
  daily: "каждый день",
  weekly: "каждую неделю",
  monthly: "каждый месяц",
  yearly: "каждый год",
};

/** Подпись для показа. Неизвестное правило (бэкенд ушёл вперёд) не ломает вид. */
export function repeatLabel(rule: string | null | undefined): string | null {
  if (!rule) return null;
  return REPEAT_LABELS[rule as RepeatRule] ?? rule;
}
